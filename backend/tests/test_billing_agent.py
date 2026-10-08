from app.llm.client import LLMClient, LLMResult
from app.llm.mock import FailingLLMClient, MockLLMClient
from app.models import ActionRecord
from tests.conftest import ADMIN, APPROVER, BILLER, make_client, sync


def confirm(client, case_id):
    r = client.post(f"/api/billing/cases/{case_id}/classification-review", headers=BILLER, json={"decision": "confirm"})
    assert r.status_code == 200, r.text
    return r.json()


def test_sync_is_idempotent(client):
    first = sync(client)
    second = client.post("/api/billing/queues/denials-team-a/sync", headers=BILLER).json()
    assert second["created"] == 0
    assert len(client.get("/api/billing/cases", headers=BILLER).json()) == len(first)


def test_paid_claim_needs_no_action(client):
    assert sync(client)["CLM-9007"]["state"] == "NO_ACTION"


def test_every_case_waits_for_human_classification_review(client):
    cases = sync(client)
    for claim_id, c in cases.items():
        if claim_id != "CLM-9007":
            assert c["state"] == "AWAITING_CLASSIFICATION_REVIEW"
            assert c["category_confirmed"] is False


def test_full_happy_path_requires_approval_and_never_submits(container, client):
    case = sync(client)["CLM-9001"]
    detail = confirm(client, case["id"])
    assert detail["state"] == "AWAITING_DRAFT_APPROVAL"
    assert detail["draft"]["type"] == "appeal_letter" and detail["gaps"] == []

    # Minimum necessary: the date-of-service note is only the claim's encounter.
    notes = [r for r in detail["retrieved_records"] if r["requirement"] == "dos_note"]
    assert [r["source"]["record_id"] for r in notes] == ["ENC-1002"]

    approved = client.post(f"/api/billing/cases/{case['id']}/draft-review", headers=APPROVER,
                           json={"decision": "approve", "note": "Looks right"}).json()
    assert approved["state"] == "ROUTED" and approved["owner"] == "Appeals specialist"

    r = client.post(f"/api/billing/cases/{case['id']}/tracking", headers=BILLER,
                    json={"status": "submitted_by_staff", "reference": "PORTAL-12345"})
    assert r.json()["state"] == "SUBMITTED_BY_STAFF"
    done = client.post(f"/api/billing/cases/{case['id']}/tracking", headers=BILLER, json={"status": "resolved"}).json()
    assert done["state"] == "COMPLETED"
    assert {s["status"] for s in done["steps"]} == {"done"}
    assert {e["step"] for e in done["events"]} >= set(range(1, 9))

    s = container.sessionmaker()
    keys = [a.key for a in s.query(ActionRecord).filter_by(case_id=case["id"])]
    assert keys.count(f"{case['id']}:route") == 1


def test_biller_cannot_approve_drafts(client):
    case = sync(client)["CLM-9001"]
    confirm(client, case["id"])
    r = client.post(f"/api/billing/cases/{case['id']}/draft-review", headers=BILLER, json={"decision": "approve"})
    assert r.status_code == 403


def test_cannot_approve_before_a_draft_exists(client):
    case = sync(client)["CLM-9001"]
    r = client.post(f"/api/billing/cases/{case['id']}/draft-review", headers=APPROVER, json={"decision": "approve"})
    assert r.status_code == 409


def test_approving_twice_is_rejected(client):
    case = sync(client)["CLM-9001"]
    confirm(client, case["id"])
    url = f"/api/billing/cases/{case['id']}/draft-review"
    assert client.post(url, headers=APPROVER, json={"decision": "approve"}).status_code == 200
    assert client.post(url, headers=APPROVER, json={"decision": "approve"}).status_code == 409


def test_missing_evidence_produces_provider_query_not_appeal(client):
    detail = confirm(client, sync(client)["CLM-9002"]["id"])
    assert {g["key"] for g in detail["gaps"]} == {"conservative_treatment", "imaging"}
    assert detail["draft"]["type"] == "provider_query"


def test_office_visit_claim_does_not_require_procedure_record(client):
    detail = confirm(client, sync(client)["CLM-9004"]["id"])
    assert detail["gaps"] == []


def test_timely_filing_is_a_hard_stop(client):
    detail = confirm(client, sync(client)["CLM-9003"]["id"])
    assert detail["state"] == "ESCALATED" and detail["draft"] is None
    assert detail["owner"] == "Billing lead"


def test_patient_mismatch_blocks_record_retrieval(client):
    detail = confirm(client, sync(client)["CLM-9005"]["id"])
    assert detail["state"] == "ESCALATED"
    assert detail["retrieved_records"] == [] and detail["meditab_patient_id"] is None
    exceptions = client.get("/api/exceptions?status=open", headers=ADMIN).json()
    assert any(e["kind"] == "billing_patient_match" and e["severity"] == "critical" for e in exceptions)


def test_prompt_injection_in_payer_text_is_flagged(client):
    case = sync(client)["CLM-9004"]
    assert "suspicious_content" in case["flags"]
    assert case["state"] == "AWAITING_CLASSIFICATION_REVIEW"  # never auto-approved


def test_hard_rule_overrides_model(client):
    case = sync(client)["CLM-9008"]
    assert case["category"] == "CODING_ERROR"
    assert "rule_overrides_model" in case["flags"]


def test_reviewer_can_change_category(client):
    case = sync(client)["CLM-9006"]
    r = client.post(f"/api/billing/cases/{case['id']}/classification-review", headers=BILLER,
                    json={"decision": "change", "category": "OTHER", "note": "Payer called back"})
    assert r.json()["classification"]["confirmed_category"] == "OTHER"


def test_model_outage_goes_to_exception_queue():
    _, client = make_client(llm=FailingLLMClient())
    cases = sync(client)
    assert cases["CLM-9001"]["state"] == "ESCALATED"
    exceptions = client.get("/api/exceptions?status=open", headers=ADMIN).json()
    assert any(e["kind"] == "llm_failure" for e in exceptions)


class UnsafeDraftLLM(MockLLMClient):
    def structured(self, *, task, **kwargs):
        if task == "billing_draft":
            return LLMResult(data={"letter_text": "Patient responded to oxycodone. This appeal has been submitted.",
                                   "evidence_ids": []}, model="stub", prompt_version="test")
        return super().structured(task=task, **kwargs)


def test_unsafe_draft_is_blocked():
    _, client = make_client(llm=UnsafeDraftLLM())
    detail = confirm(client, sync(client)["CLM-9001"]["id"])
    assert detail["state"] == "ESCALATED" and detail["draft"] is None
    assert "safety checks" in detail["escalation_reason"]


def test_reject_then_redraft_increments_version(client):
    case = sync(client)["CLM-9001"]
    confirm(client, case["id"])
    url = f"/api/billing/cases/{case['id']}"
    assert client.post(f"{url}/draft-review", headers=APPROVER, json={"decision": "reject"}).status_code == 422
    rejected = client.post(f"{url}/draft-review", headers=APPROVER, json={"decision": "reject", "note": "Shorter"}).json()
    assert rejected["state"] == "DRAFT_REJECTED"
    redrafted = client.post(f"{url}/advance", headers=BILLER).json()
    assert redrafted["state"] == "AWAITING_DRAFT_APPROVAL" and redrafted["draft"]["version"] == 2


def test_human_edit_is_recorded(client):
    case = sync(client)["CLM-9006"]
    confirm(client, case["id"])
    approved = client.post(f"/api/billing/cases/{case['id']}/draft-review", headers=APPROVER,
                           json={"decision": "approve", "edited_text": "Edited follow-up text."}).json()
    assert approved["draft"]["source"] == "human_edited" and approved["draft"]["text"] == "Edited follow-up text."
