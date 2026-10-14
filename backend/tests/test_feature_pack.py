"""Tests for the feature pack: AI gateway, summary reuse, documentation audit, billing insights, acceptance."""
import pytest

from app.config import Settings
from app.models import LLMCall
from app.services.patient_matching import PatientMatcher
from tests.conftest import ADMIN, APPROVER, BILLER, PROVIDER, make_client, sync


# ------------------------------------------------------------------ AI gateway
def test_every_model_call_is_metered(container, client):
    sync(client)
    s = container.sessionmaker()
    tasks = {c.task for c in s.query(LLMCall).filter_by(status="ok")}
    assert "billing_classify" in tasks


def test_kill_switch_stops_ai_and_cases_go_to_exception_queue(client):
    r = client.post("/api/ai/pause", headers=ADMIN, json={"paused": True, "reason": "demo"})
    assert r.json()["paused"] is True
    cases = sync(client)
    assert cases["CLM-9001"]["state"] == "ESCALATED"
    summary = client.post("/api/patients/SYN-P-0001/previsit-summary", headers=PROVIDER).json()
    assert summary["status"] == "failed"
    usage = client.get("/api/ai/usage", headers=ADMIN).json()
    assert any(t["blocked"] for t in usage["by_task"])


def test_only_admin_can_pause_ai(client):
    assert client.post("/api/ai/pause", headers=APPROVER, json={"paused": True}).status_code == 403


def test_monthly_budget_blocks_calls():
    from datetime import date

    from app.container import build_container
    from app.llm.client import LLMClient, LLMResult
    from app.main import create_app
    from fastapi.testclient import TestClient

    class Costly(LLMClient):
        name = "costly"

        def structured(self, **kw):
            from app.llm.mock import MockLLMClient
            r = MockLLMClient().structured(**kw)
            return LLMResult(data=r.data, model="m", prompt_version=r.prompt_version, input_tokens=600, output_tokens=0)

    c = build_container(Settings(database_url="sqlite:///:memory:", llm_provider="mock", as_of_date=date(2026, 9, 1),
                                 llm_monthly_token_budget=1000), llm=Costly())
    client = TestClient(create_app(c))
    cases = sync(client)
    states = sorted(x["state"] for x in cases.values() if x["claim_id"] != "CLM-9007")
    assert "ESCALATED" in states and "AWAITING_CLASSIFICATION_REVIEW" in states


# ------------------------------------------------------------------ summary reuse
def test_unchanged_chart_reuses_summary_and_force_regenerates(container, client):
    first = client.post("/api/patients/SYN-P-0001/previsit-summary", headers=PROVIDER).json()
    second = client.post("/api/patients/SYN-P-0001/previsit-summary", headers=PROVIDER).json()
    assert first["reused"] is False and second["reused"] is True
    assert second["statements"] == first["statements"]
    third = client.post("/api/patients/SYN-P-0001/previsit-summary?force=true", headers=PROVIDER).json()
    assert third["reused"] is False
    s = container.sessionmaker()
    assert s.query(LLMCall).filter_by(task="previsit_summary", status="reused").count() == 1


# ------------------------------------------------------------------ documentation audit
def test_doc_audit_finds_expected_gaps_with_evidence(client):
    r = client.post("/api/patients/SYN-P-0002/documentation-audit", headers=PROVIDER).json()
    got = {(f["rule_id"], f["target"]) for f in r["findings"]}
    assert got == {("DA-01", "ENC-2002"), ("DA-03", "patient"), ("DA-04", "patient"), ("DA-06", "ENC-2002"), ("DA-07", "ENC-2002")}
    assert r["checks_total"] == r["checks_passed"] + len(r["findings"])
    enc_findings = [f for f in r["findings"] if f["target"].startswith("ENC")]
    assert all(f["evidence"] and f["evidence"][0]["source"]["record_id"] for f in enc_findings)


def test_ai_claim_without_verbatim_quote_becomes_finding():
    from app.llm.mock import MockLLMClient

    class Overclaiming(MockLLMClient):
        def structured(self, *, task, **kw):
            r = super().structured(task=task, **kw)
            if task == "doc_audit_notes":
                for c in r.data["checks"]:
                    c["met"], c["evidence_quote"] = True, "Plan: invented text that is not in the note"
            return r

    _, client = make_client(llm=Overclaiming())
    r = client.post("/api/patients/SYN-P-0003/documentation-audit", headers=PROVIDER).json()
    ai = [f for f in r["findings"] if f["rule_id"] == "DA-06"]
    assert ai and "quote is not in the note" in ai[0]["message"]


def test_finding_review_rules(client):
    r = client.post("/api/patients/SYN-P-0002/documentation-audit", headers=PROVIDER).json()
    fid = r["findings"][0]["id"]
    url = f"/api/documentation-audit/findings/{fid}/review"
    assert client.post(url, headers=ADMIN, json={"decision": "confirmed"}).status_code == 403
    assert client.post(url, headers=PROVIDER, json={"decision": "dismissed"}).status_code == 422
    ok = client.post(url, headers=PROVIDER, json={"decision": "confirmed"}).json()
    assert next(f for f in ok["findings"] if f["id"] == fid)["status"] == "confirmed"
    assert client.post(url, headers=PROVIDER, json={"decision": "confirmed"}).status_code == 409


def test_billing_staff_cannot_run_clinical_audit(client):
    assert client.post("/api/patients/SYN-P-0001/documentation-audit", headers=BILLER).status_code == 403


# ------------------------------------------------------------------ billing insights
def test_insights_measure_accuracy_usability_and_time(client):
    cases = sync(client)
    cid = cases["CLM-9001"]["id"]
    client.post(f"/api/billing/cases/{cid}/classification-review", headers=BILLER,
                json={"decision": "confirm", "handling_seconds": 120})
    client.post(f"/api/billing/cases/{cid}/draft-review", headers=APPROVER,
                json={"decision": "approve", "edit_level": "minor", "handling_seconds": 600})
    assert client.post("/api/billing/baselines/demo", headers=APPROVER).json()["synthetic"] is True

    m = client.get("/api/billing/insights", headers=BILLER).json()
    assert m["classification"]["reviewed"] == 1 and m["classification"]["proposal_accuracy"] == 1.0
    assert m["drafts"] == {"rated": 1, "usable": 1, "usable_rate": 1.0, "ratings": {"minor": 1}}
    mn = next(r for r in m["handling_time"]["by_category"] if r["category"] == "MEDICAL_NECESSITY")
    assert mn["avg_minutes_with_agent"] == 12.0 and mn["baseline_minutes"] == 38.0
    assert m["handling_time"]["baseline_synthetic"] is True
    assert m["money"]["appeals_with_owner"] == 1450.0

    csv_text = client.get("/api/billing/insights.csv", headers=BILLER).text
    assert csv_text.splitlines()[0].startswith("claim_id,payer")
    assert "CLM-9001" in csv_text


def test_handling_time_is_capped(container, client):
    from app.models import CaseEvent

    cid = sync(client)["CLM-9006"]["id"]
    client.post(f"/api/billing/cases/{cid}/classification-review", headers=BILLER,
                json={"decision": "confirm", "handling_seconds": 86400})
    s = container.sessionmaker()
    recorded = [e.detail["handling_seconds"] for e in s.query(CaseEvent).filter_by(case_id=cid)
                if (e.detail or {}).get("handling_seconds")]
    assert recorded == [4 * 3600]  # a tab left open overnight can't inflate the numbers


def test_baseline_needs_permission_and_valid_category(client):
    body = {"category": "MEDICAL_NECESSITY", "minutes_per_case": 30, "sample_size": 12, "source": "Time study"}
    assert client.post("/api/billing/baselines", headers=BILLER, json=body).status_code == 403
    assert client.post("/api/billing/baselines", headers=APPROVER, json=body | {"category": "NOPE"}).status_code == 422
    assert client.post("/api/billing/baselines", headers=APPROVER, json=body).status_code == 200


def test_providers_cannot_see_billing_insights(client):
    assert client.get("/api/billing/insights", headers=PROVIDER).status_code == 403


# ------------------------------------------------------------------ acceptance scorecard
def test_acceptance_run_has_no_hard_gate_failures(client):
    r = client.post("/api/acceptance/run", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["hard_gate_failures"] == []
    assert len(body["results"]) == 15
    by_id = {x["id"]: x for x in body["results"]}
    assert by_id["C01"]["status"] == "pass" and by_id["C14"]["status"] == "pass"
    assert by_id["C06"]["status"] == "not_testable"
    assert client.get("/api/acceptance/runs", headers=PROVIDER).json()[0]["id"] == body["id"]


def test_acceptance_does_not_touch_live_data(container, client):
    client.post("/api/acceptance/run", headers=ADMIN)
    assert client.get("/api/billing/cases", headers=BILLER).json() == []


def test_acceptance_catches_a_broken_safety_control(client, monkeypatch):
    monkeypatch.setattr(PatientMatcher, "_cross_check", staticmethod(lambda *a, **k: []))
    body = client.post("/api/acceptance/run", headers=ADMIN).json()
    assert "C01" in body["summary"]["hard_gate_failures"]
    assert any("PM-03" in f for f in next(x for x in body["results"] if x["id"] == "C01")["failures"])


def test_only_admin_runs_acceptance(client):
    assert client.post("/api/acceptance/run", headers=APPROVER).status_code == 403


def test_acceptance_refuses_when_ai_paused(client):
    client.post("/api/ai/pause", headers=ADMIN, json={"paused": True})
    assert client.post("/api/acceptance/run", headers=ADMIN).status_code == 409
