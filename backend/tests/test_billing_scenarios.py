"""Where every synthetic claim should end up after a biller confirms its proposed category."""
import pytest

from tests.conftest import BILLER, sync

# claim -> (proposed category, final state, draft type, gaps, flags that must be present)
EXPECTED = {
    "CLM-9001": ("MEDICAL_NECESSITY", "AWAITING_DRAFT_APPROVAL", "appeal_letter", [], []),
    "CLM-9002": ("MEDICAL_NECESSITY", "AWAITING_DRAFT_APPROVAL", "provider_query", ["conservative_treatment", "imaging"], []),
    "CLM-9003": ("TIMELY_FILING", "ESCALATED", None, [], []),
    "CLM-9004": ("MISSING_DOCUMENTATION", "AWAITING_DRAFT_APPROVAL", "appeal_letter", [], ["suspicious_content"]),
    "CLM-9005": ("CODING_ERROR", "ESCALATED", None, [], []),
    "CLM-9006": ("NO_PAYER_RESPONSE", "AWAITING_DRAFT_APPROVAL", "payer_follow_up", [], []),
    "CLM-9008": ("CODING_ERROR", "AWAITING_DRAFT_APPROVAL", "coding_review", [], ["rule_overrides_model"]),
    "CLM-9009": ("MEDICAL_NECESSITY", "AWAITING_DRAFT_APPROVAL", "appeal_letter", [], []),
    "CLM-9010": ("MISSING_PRIOR_AUTH", "AWAITING_DRAFT_APPROVAL", "appeal_letter", [], []),
    "CLM-9011": ("MEDICAL_NECESSITY", "AWAITING_DRAFT_APPROVAL", "provider_query", ["conservative_treatment", "imaging"], []),
    "CLM-9012": ("MISSING_PRIOR_AUTH", "AWAITING_DRAFT_APPROVAL", "provider_query", ["auth_record"], []),
    "CLM-9013": ("MISSING_DOCUMENTATION", "AWAITING_DRAFT_APPROVAL", "appeal_letter", [], ["low_confidence"]),
    "CLM-9014": ("CODING_ERROR", "AWAITING_DRAFT_APPROVAL", "coding_review", [], []),
    "CLM-9015": ("ELIGIBILITY", "ESCALATED", None, [], []),
    "CLM-9016": ("ELIGIBILITY", "ESCALATED", None, [], []),
    "CLM-9017": ("DUPLICATE", "ESCALATED", None, [], []),
    "CLM-9018": ("NO_PAYER_RESPONSE", "AWAITING_DRAFT_APPROVAL", "payer_follow_up", [], []),
    "CLM-9021": ("CODING_ERROR", "AWAITING_DRAFT_APPROVAL", "coding_review", [], []),
    "CLM-9022": ("NO_PAYER_RESPONSE", "AWAITING_DRAFT_APPROVAL", "payer_follow_up", [], []),
    "CLM-9023": ("MISSING_DOCUMENTATION", "AWAITING_DRAFT_APPROVAL", "provider_query", ["dos_procedure"], []),
    "CLM-9025": ("MISSING_DOCUMENTATION", "AWAITING_DRAFT_APPROVAL", "provider_query", ["dos_procedure"], ["suspicious_content"]),
    "CLM-9026": ("MEDICAL_NECESSITY", "ESCALATED", None, [], []),
    "CLM-9027": ("MEDICAL_NECESSITY", "AWAITING_DRAFT_APPROVAL", "appeal_letter", [], []),
    "CLM-9028": ("TIMELY_FILING", "ESCALATED", None, [], []),
    "CLM-9029": ("NO_PAYER_RESPONSE", "AWAITING_DRAFT_APPROVAL", "payer_follow_up", [], []),
    "CLM-9030": ("OTHER", "AWAITING_DRAFT_APPROVAL", "appeal_letter", [], ["low_confidence"]),
    "CLM-9090": ("CODING_ERROR", "ESCALATED", None, [], ["rule_overrides_model"]),
}
NO_ACTION = {"CLM-9007", "CLM-9019", "CLM-9020", "CLM-9024"}
PATIENT_STOPS = {"CLM-9005", "CLM-9026", "CLM-9090"}


def test_queue_has_at_least_25_work_items(client):
    cases = sync(client)
    work = [c for c in cases.values() if c["state"] != "NO_ACTION"]
    assert len(cases) == 31 and len(work) == 27
    assert set(cases) == set(EXPECTED) | NO_ACTION


@pytest.fixture(scope="module")
def worked():
    from tests.conftest import make_client

    _, client = make_client()
    cases = sync(client)
    out = {}
    for claim, c in cases.items():
        if c["state"] == "AWAITING_CLASSIFICATION_REVIEW":
            r = client.post(f"/api/billing/cases/{c['id']}/classification-review", headers=BILLER, json={"decision": "confirm"})
            out[claim] = r.json()
        else:
            out[claim] = c
    return out


@pytest.mark.parametrize("claim", sorted(EXPECTED))
def test_claim_scenario(worked, claim):
    category, state, draft, gaps, flags = EXPECTED[claim]
    d = worked[claim]
    assert d["classification"]["proposed_category"] == category
    assert d["state"] == state
    assert (d["draft"]["type"] if d["draft"] else None) == draft
    assert sorted(g["key"] for g in d["gaps"]) == sorted(gaps)
    for f in flags:
        assert f in d["flags"]
    if claim in PATIENT_STOPS:
        assert d["retrieved_records"] == [] and d["meditab_patient_id"] is None


# ------------------------------------------------------------------ demo workload (status mix)
def test_demo_workload_creates_realistic_status_mix(client):
    from collections import Counter

    from tests.conftest import ADMIN, APPROVER

    r = client.post("/api/billing/queues/denials-team-a/demo-workload", headers=APPROVER).json()
    assert r["problems"] == [] and len(r["moved"]) == 15
    states = Counter(c["state"] for c in client.get("/api/billing/cases", headers=BILLER).json())
    assert states == {"AWAITING_CLASSIFICATION_REVIEW": 12, "AWAITING_DRAFT_APPROVAL": 5, "NO_ACTION": 4, "COMPLETED": 3,
                      "ROUTED": 2, "ESCALATED": 2, "SUBMITTED_BY_STAFF": 2, "DRAFT_REJECTED": 1}
    again = client.post("/api/billing/queues/denials-team-a/demo-workload", headers=ADMIN).json()
    assert again["moved"] == []


def test_demo_script_cases_stay_at_review(client):
    from tests.conftest import APPROVER

    client.post("/api/billing/queues/denials-team-a/demo-workload", headers=APPROVER)
    cases = {c["claim_id"]: c for c in client.get("/api/billing/cases", headers=BILLER).json()}
    for claim in ("CLM-9001", "CLM-9003", "CLM-9004", "CLM-9005", "CLM-9006", "CLM-9008", "CLM-9026", "CLM-9090"):
        assert cases[claim]["state"] == "AWAITING_CLASSIFICATION_REVIEW", claim


def test_demo_decisions_are_not_counted_as_evidence(client):
    from tests.conftest import APPROVER

    client.post("/api/billing/queues/denials-team-a/demo-workload", headers=APPROVER)
    m = client.get("/api/billing/insights", headers=BILLER).json()
    assert m["classification"]["reviewed"] == 0 and m["drafts"]["rated"] == 0
    assert m["demo_seeded_cases"] == 15
    assert m["volume"]["completed"] == 3  # volume and money still reflect the queue


def test_demo_workload_needs_permission(client):
    assert client.post("/api/billing/queues/denials-team-a/demo-workload", headers=BILLER).status_code == 403
