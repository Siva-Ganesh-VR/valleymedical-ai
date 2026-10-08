"""Deterministic offline LLM for demos without an API key, and for tests.

It produces plausible, correctly cited output from the structured `context` that callers
pass alongside the prompt. It is NOT a model and must never be used to judge accuracy.
"""
from __future__ import annotations

from app.llm.client import LLMClient, LLMError, LLMResult

_CARC_TO_CATEGORY = {
    "50": "MEDICAL_NECESSITY",
    "197": "MISSING_PRIOR_AUTH",
    "16": "MISSING_DOCUMENTATION",
    "11": "CODING_ERROR",
    "4": "CODING_ERROR",
    "27": "ELIGIBILITY",
    "31": "ELIGIBILITY",
    "29": "TIMELY_FILING",
    "18": "DUPLICATE",
}


class MockLLMClient(LLMClient):
    name = "mock"
    model = "mock-llm"

    def structured(self, *, task, system, user, tool_name, tool_description, schema,
                   prompt_version, context=None) -> LLMResult:
        context = context or {}
        handler = {
            "previsit_summary": self._previsit,
            "billing_classify": self._classify,
            "billing_draft": self._draft,
        }.get(task)
        if handler is None:
            raise LLMError(f"Mock LLM has no handler for task '{task}'")
        return LLMResult(data=handler(context), model=self.model, prompt_version=prompt_version)

    @staticmethod
    def _previsit(ctx: dict) -> dict:
        statements = []
        for ev in ctx.get("evidence", []):
            d, eid, section = ev["data"], ev["id"], ev["section"]
            if section == "problems":
                statements.append(("problems", f"Active problem: {d['description']} ({d['icd10']}).", eid))
            elif section == "medications" and d.get("status") == "active":
                statements.append(("medications", f"Current medication: {d['name']} {d['dose']} {d['frequency']}.", eid))
            elif section == "allergies":
                statements.append(("allergies", f"Allergy to {d['substance']} ({d['reaction']}).", eid))
            elif section == "procedures":
                statements.append(("recent_care", f"{d['name']} on {d['performed_on']}.", eid))
        pain = [ev for ev in ctx.get("evidence", []) if ev["section"] == "observations" and ev["data"].get("dimension") == "pain"]
        if pain:
            latest = max(pain, key=lambda e: e["data"]["recorded_on"])
            statements.append(("pain_trend", f"Most recent pain score {latest['data']['display_value']} on {latest['data']['recorded_on']}.", latest["id"]))
        return {"statements": [{"section": s, "text": t, "evidence_ids": [e]} for s, t, e in statements]}

    @staticmethod
    def _classify(ctx: dict) -> dict:
        if ctx.get("problem_type") == "unworked":
            return {"category": "NO_PAYER_RESPONSE", "confidence": 0.85,
                    "rationale": "Claim is pending with no payer decision and has not been worked recently.",
                    "recommended_next_action": "Send a claim-status inquiry to the payer."}
        category = _CARC_TO_CATEGORY.get(str(ctx.get("carc_code") or ""))
        if category:
            return {"category": category, "confidence": 0.9,
                    "rationale": f"Denial reason code {ctx.get('carc_code')} indicates {category.replace('_', ' ').lower()}.",
                    "recommended_next_action": "Gather supporting records and prepare the appropriate response."}
        return {"category": "OTHER", "confidence": 0.5, "rationale": "Denial reason is unclear from the claim data.",
                "recommended_next_action": "Review the remittance details manually."}

    @staticmethod
    def _draft(ctx: dict) -> dict:
        claim, evidence, gaps = ctx["claim"], ctx.get("evidence", []), ctx.get("gaps", [])
        draft_type = ctx["draft_type"]
        if draft_type == "provider_query":
            lines = [
                "To: Treating provider",
                f"Re: Documentation needed for claim {claim['claim_id']}, date of service {claim['date_of_service']}",
                "",
                f"The payer ({claim['payer']}) denied this claim: {claim.get('denial_description') or 'see remittance'}.",
                "Before an appeal can be prepared, please confirm whether the following documentation exists or can be added:",
                *[f"- {g['label']}" for g in gaps],
                "",
                "Billing Office",
            ]
            return {"letter_text": "\n".join(lines), "evidence_ids": []}
        if draft_type == "payer_follow_up":
            lines = [
                f"To: {claim['payer']}, Claims Department",
                f"Re: Status inquiry for claim {claim['claim_id']}, date of service {claim['date_of_service']}",
                "",
                f"This claim was submitted on {claim.get('submitted_on')} and we have not received a determination.",
                "Please provide the current status and any information needed to complete processing.",
                "",
                "Billing Office",
            ]
            return {"letter_text": "\n".join(lines), "evidence_ids": []}
        if draft_type == "coding_review":
            lines = [
                "To: Coding specialist",
                f"Re: Code review for claim {claim['claim_id']}, date of service {claim['date_of_service']}",
                "",
                f"The payer returned this claim: {claim.get('denial_description') or 'see remittance'}.",
                f"Billed CPT: {', '.join(claim['cpt_codes'])}. Billed diagnosis codes: {', '.join(claim['icd10_codes']) or 'none'}.",
                "Documentation in the record for review:",
                *[f"- {ev['text']} [{ev['id']}]" for ev in evidence],
                "",
                "Please review and correct the codes if the documentation supports it.",
                "",
                "Billing Office",
            ]
            return {"letter_text": "\n".join(lines), "evidence_ids": [ev["id"] for ev in evidence]}
        lines = [
            f"To: {claim['payer']}, Appeals Department",
            f"Re: Request for reconsideration, claim {claim['claim_id']}, date of service {claim['date_of_service']}",
            "",
            f"We request reconsideration of the denial (reason code {claim.get('denial_code')}) for CPT {', '.join(claim['cpt_codes'])}.",
            "The patient's records document the following:",
            *[f"- {ev['text']} [{ev['id']}]" for ev in evidence],
            "",
            "We ask that the claim be reprocessed based on this documentation.",
            "",
            "Billing Office",
        ]
        return {"letter_text": "\n".join(lines), "evidence_ids": [ev["id"] for ev in evidence]}


class FailingLLMClient(LLMClient):
    """Always fails. Used in tests to prove failures go to the exception queue."""

    name = "failing"

    def structured(self, **kwargs) -> LLMResult:
        raise LLMError("Model unavailable after 3 attempts: APIConnectionError")
