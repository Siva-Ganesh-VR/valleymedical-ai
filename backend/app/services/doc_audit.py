"""AI-23 clinical documentation audit (WBS #10).

Deterministic rules run first. Narrative rules ("does the note document a plan?") use the model,
and every "met" answer must quote the note verbatim: a quote that is not in the note is treated
as unverified and raised as a finding for a person to review. Each finding links to the Meditab
record it is about, and clinicians confirm or dismiss findings, which measures audit accuracy.

ILLUSTRATIVE RULES: Valley Medical's own documentation rules are a client dependency (due end of
Month 1). These seven show the mechanism and are replaced, not extended, when the real rules arrive.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import AuditLogger
from app.errors import InvalidStateError, NotFoundError, ValidationFailedError
from app.llm import prompts
from app.llm.client import LLMClient, LLMError
from app.models import DocAuditFinding, DocAuditRun, utcnow_iso
from app.security import Actor
from app.services.clinical_record import ClinicalRecord, ClinicalRecordService, RecordItem

RULESET_VERSION = "doc_audit_rules/0.1.0-illustrative"
PAIN_ICD_PREFIXES = ("M54", "M25", "M79", "G89", "M17", "M47", "M51")
VISIT_TYPES = ("office visit", "follow-up visit", "procedure visit")


@dataclass(frozen=True)
class AuditRule:
    rule_id: str
    title: str
    description: str
    method: str  # rule | ai
    severity: str  # high | medium


RULES: list[AuditRule] = [
    AuditRule("DA-01", "Pain score at every visit",
              "For patients with a pain diagnosis, every office, follow-up and procedure visit records a pain score.",
              "rule", "high"),
    AuditRule("DA-02", "Function measured at follow-up",
              "Every follow-up visit for a pain patient records a functional measure (for example the Oswestry Disability Index).",
              "rule", "medium"),
    AuditRule("DA-03", "Mood screened in the last 12 months",
              "Pain patients have a mood screening (for example PHQ-9) within the last 12 months.", "rule", "medium"),
    AuditRule("DA-04", "Allergy status documented",
              "The chart lists allergies, or explicitly records no known allergies.", "rule", "high"),
    AuditRule("DA-05", "Procedures linked to a visit note",
              "Every procedure is linked to an encounter that has a note.", "rule", "medium"),
    AuditRule("DA-06", "Visit note documents a plan",
              "Each visit note states a plan or next steps.", "ai", "medium"),
    AuditRule("DA-07", "Procedure note documents the indication",
              "Each procedure visit note states why the procedure was performed.", "ai", "high"),
]
RULES_BY_ID = {r.rule_id: r for r in RULES}


def _evidence(item: RecordItem) -> dict:
    return {"item_id": item.item_id, "display": item.display[:400], "source": item.source.model_dump(mode="json")}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class DocumentationAuditService:
    def __init__(self, session: Session, records: ClinicalRecordService, llm: LLMClient, audit: AuditLogger,
                 clock: Callable[[], date]):
        self._s = session
        self._records = records
        self._llm = llm
        self._audit = audit
        self._clock = clock

    # ------------------------------------------------------------------ run
    def run(self, patient_id: str, actor: Actor) -> dict:
        record = self._records.get_record(patient_id, actor=actor, purpose="documentation_audit")
        passed: list[dict] = []
        findings: list[dict] = []
        not_checked: list[str] = []

        def ok(rule_id: str, target: str, evidence: list[dict], note: str) -> None:
            passed.append({"rule_id": rule_id, "target": target, "note": note, "evidence": evidence})

        def fail(rule_id: str, target: str, message: str, evidence: list[dict], method: str | None = None) -> None:
            rule = RULES_BY_ID[rule_id]
            findings.append({"rule_id": rule_id, "target": target, "message": message, "evidence": evidence,
                             "severity": rule.severity, "method": method or rule.method})

        unavailable = set(record.unavailable_sections())
        self._deterministic(record, ok, fail, unavailable, not_checked)
        model, prompt_version = self._narrative(record, ok, fail, unavailable, not_checked)

        total = len(passed) + len(findings)
        run = DocAuditRun(patient_id=patient_id, created_at=utcnow_iso(), actor=actor.username,
                          ruleset_version=RULESET_VERSION, checks_total=total, checks_passed=len(passed),
                          model=model, prompt_version=prompt_version,
                          detail={"passed": passed, "not_checked": not_checked})
        self._s.add(run)
        self._s.flush()
        for f in findings:
            self._s.add(DocAuditFinding(run_id=run.id, patient_id=patient_id, **f))
        self._s.flush()
        self._audit.record(actor=actor, action="doc_audit.run", entity_type="patient", entity_id=patient_id,
                           patient_ref=patient_id, purpose="documentation_audit", model=model, prompt_version=prompt_version,
                           detail={"run_id": run.id, "checks": total, "findings": len(findings), "ruleset": RULESET_VERSION})
        return self.view(run)

    def _deterministic(self, record: ClinicalRecord, ok, fail, unavailable: set[str], not_checked: list[str]) -> None:
        items = record.items
        problems = items.get("problems", [])
        pain_patient = any(str(p.data.get("icd10", "")).startswith(PAIN_ICD_PREFIXES) or "pain" in str(p.data.get("description", "")).lower()
                           for p in problems)
        observations = items.get("observations", [])
        obs_by_enc: dict[str, dict[str, list[RecordItem]]] = {}
        for o in observations:
            enc = o.source.encounter_id
            if enc:
                obs_by_enc.setdefault(enc, {}).setdefault(str(o.data.get("dimension")), []).append(o)
        encounters = items.get("encounters", [])

        if pain_patient and "observations" not in unavailable:
            for enc in encounters:
                etype = str(enc.data.get("type", "")).lower()
                eid = enc.source.record_id
                if etype in VISIT_TYPES:
                    pain = obs_by_enc.get(eid, {}).get("pain", [])
                    if pain:
                        ok("DA-01", eid, [_evidence(enc), _evidence(pain[0])], f"Pain score {pain[0].data.get('display_value')} recorded")
                    else:
                        fail("DA-01", eid, f"No pain score recorded for the {etype} on {enc.date}.", [_evidence(enc)])
                if etype == "follow-up visit":
                    fn = obs_by_enc.get(eid, {}).get("function", [])
                    if fn:
                        ok("DA-02", eid, [_evidence(enc), _evidence(fn[0])], f"{fn[0].data.get('instrument')} recorded")
                    else:
                        fail("DA-02", eid, f"No functional measure recorded for the follow-up visit on {enc.date}.", [_evidence(enc)])
            since = self._clock() - timedelta(days=365)
            mood = [o for o in observations if o.data.get("dimension") == "mood" and o.date and o.date >= since]
            if mood:
                latest = max(mood, key=lambda o: o.date)
                ok("DA-03", "patient", [_evidence(latest)], f"{latest.data.get('instrument')} on {latest.date}")
            else:
                fail("DA-03", "patient", "No mood screening recorded in the last 12 months.", [])
        elif "observations" in unavailable:
            not_checked += ["DA-01", "DA-02", "DA-03"]

        if "allergies" in unavailable:
            not_checked.append("DA-04")
        elif items.get("allergies"):
            ok("DA-04", "patient", [_evidence(a) for a in items["allergies"]], f"{len(items['allergies'])} allergy record(s)")
        else:
            fail("DA-04", "patient", "No allergies and no 'no known allergies' entry in the chart.", [])

        if "procedures" not in unavailable:
            enc_ids = {e.source.record_id for e in encounters}
            for proc in items.get("procedures", []):
                link = proc.source.encounter_id
                if link and link in enc_ids:
                    enc = next(e for e in encounters if e.source.record_id == link)
                    ok("DA-05", proc.source.record_id, [_evidence(proc), _evidence(enc)], f"Linked to {link}")
                else:
                    fail("DA-05", proc.source.record_id,
                         f"'{proc.data.get('name')}' on {proc.date} is not linked to a visit note.", [_evidence(proc)])
        else:
            not_checked.append("DA-05")

    def _narrative(self, record: ClinicalRecord, ok, fail, unavailable: set[str], not_checked: list[str]) -> tuple[str | None, str | None]:
        if "encounters" in unavailable:
            not_checked += ["DA-06", "DA-07"]
            return None, None
        encounters = record.items.get("encounters", [])
        if not encounters:
            return None, None
        notes = {e.source.record_id: str(e.data.get("note_text", "")) for e in encounters}
        enc_by_id = {e.source.record_id: e for e in encounters}
        pairs = [{"rule_id": "DA-06", "encounter_id": eid} for eid in notes]
        pairs += [{"rule_id": "DA-07", "encounter_id": e.source.record_id} for e in encounters
                  if "procedure" in str(e.data.get("type", "")).lower()]
        rules = [{"rule_id": r.rule_id, "description": r.description} for r in RULES if r.method == "ai"]
        note_list = [{"encounter_id": eid, "date": enc_by_id[eid].date, "type": enc_by_id[eid].data.get("type"), "note": text}
                     for eid, text in notes.items()]
        try:
            result = self._llm.structured(
                task="doc_audit_notes", system=prompts.DOC_AUDIT_SYSTEM,
                user=prompts.doc_audit_user(rules, note_list, pairs), tool_name=prompts.DOC_AUDIT_TOOL,
                tool_description="Return one check per requested (rule, note) pair.", schema=prompts.DOC_AUDIT_SCHEMA,
                prompt_version=prompts.DOC_AUDIT_PROMPT_VERSION, context={"notes": note_list, "pairs": pairs},
            )
        except LLMError as exc:
            for pair in pairs:
                fail(pair["rule_id"], pair["encounter_id"], f"Could not be checked: {exc}. Review manually.",
                     [_evidence(enc_by_id[pair["encounter_id"]])], method="ai")
            return None, prompts.DOC_AUDIT_PROMPT_VERSION

        answers = {(str(c.get("rule_id")), str(c.get("encounter_id"))): c for c in result.data.get("checks", [])}
        for pair in pairs:
            key = (pair["rule_id"], pair["encounter_id"])
            enc = enc_by_id[pair["encounter_id"]]
            answer = answers.get(key)
            if answer is None:
                fail(*key, "The model did not check this note. Review manually.", [_evidence(enc)])
                continue
            quote = str(answer.get("evidence_quote") or "").strip()
            if answer.get("met") is True:
                if quote and _norm(quote) in _norm(notes[pair["encounter_id"]]):
                    ok(*key, [_evidence(enc)], f'Note says: "{quote[:200]}"')
                else:
                    fail(*key, "The model said this was met, but its quote is not in the note. Review manually.",
                         [_evidence(enc)])
            else:
                rule = RULES_BY_ID[pair["rule_id"]]
                fail(*key, f"{rule.title}: not found in the note for {enc.date}.", [_evidence(enc)])
        return result.model, result.prompt_version

    # ------------------------------------------------------------------ read and review
    def latest(self, patient_id: str) -> dict | None:
        run = self._s.scalars(select(DocAuditRun).where(DocAuditRun.patient_id == patient_id)
                              .order_by(DocAuditRun.id.desc()).limit(1)).first()
        return self.view(run) if run else None

    def view(self, run: DocAuditRun) -> dict:
        findings = list(self._s.scalars(select(DocAuditFinding).where(DocAuditFinding.run_id == run.id)
                                        .order_by(DocAuditFinding.id)))
        return {
            "run_id": run.id, "patient_id": run.patient_id, "created_at": run.created_at, "actor": run.actor,
            "ruleset_version": run.ruleset_version, "model": run.model, "prompt_version": run.prompt_version,
            "checks_total": run.checks_total, "checks_passed": run.checks_passed,
            "score": round(run.checks_passed / run.checks_total, 3) if run.checks_total else None,
            "rules": [asdict(r) for r in RULES],
            "passed": run.detail.get("passed", []),
            "not_checked": run.detail.get("not_checked", []),
            "findings": [{
                "id": f.id, "rule_id": f.rule_id, "rule_title": RULES_BY_ID[f.rule_id].title, "target": f.target,
                "severity": f.severity, "method": f.method, "message": f.message, "evidence": f.evidence,
                "status": f.status, "reviewed_by": f.reviewed_by, "review_note": f.review_note,
            } for f in findings],
        }

    def review(self, finding_id: int, actor: Actor, decision: str, note: str | None) -> dict:
        finding = self._s.get(DocAuditFinding, finding_id)
        if finding is None:
            raise NotFoundError(f"Finding {finding_id} not found")
        if decision not in ("confirmed", "dismissed"):
            raise ValidationFailedError("decision must be 'confirmed' or 'dismissed'")
        if decision == "dismissed" and not (note and note.strip()):
            raise ValidationFailedError("Say why the finding is wrong when dismissing it")
        if finding.status != "open":
            raise InvalidStateError(f"Finding is already {finding.status}")
        finding.status, finding.reviewed_by, finding.review_note = decision, actor.username, note
        finding.reviewed_at = utcnow_iso()
        self._audit.record(actor=actor, action=f"doc_audit.finding.{decision}", entity_type="doc_audit_finding",
                           entity_id=str(finding.id), patient_ref=finding.patient_id,
                           detail={"rule_id": finding.rule_id, "target": finding.target})
        run = self._s.get(DocAuditRun, finding.run_id)
        return self.view(run)

    def reviewer_accuracy(self) -> dict:
        reviewed = list(self._s.scalars(select(DocAuditFinding).where(DocAuditFinding.status.in_(("confirmed", "dismissed")))))
        confirmed = sum(1 for f in reviewed if f.status == "confirmed")
        return {"reviewed": len(reviewed), "confirmed": confirmed,
                "accuracy": round(confirmed / len(reviewed), 3) if reviewed else None}
