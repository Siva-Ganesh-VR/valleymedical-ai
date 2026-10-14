"""Regressions for issues seen in the 8 Oct 2026 demo recordings."""
from tests.conftest import ADMIN, APPROVER, BILLER, sync


def statuses(detail):
    return {s["step"]: s["status"] for s in detail["steps"]}


def test_escalated_case_shows_where_it_stopped(client):
    # Same pattern as CLM-9090 in the video: category changed, then the patient can't be matched.
    case = sync(client)["CLM-9005"]
    d = client.post(f"/api/billing/cases/{case['id']}/classification-review", headers=APPROVER,
                    json={"decision": "change", "category": "ELIGIBILITY"}).json()
    assert d["state"] == "ESCALATED"
    s = statuses(d)
    assert [s[n] for n in (1, 2, 3)] == ["done"] * 3
    assert s[4] == "blocked"
    assert [s[n] for n in (5, 6, 7, 8)] == ["not_reached"] * 4


def test_resolving_does_not_pretend_skipped_steps_ran(client):
    case = sync(client)["CLM-9005"]
    client.post(f"/api/billing/cases/{case['id']}/classification-review", headers=APPROVER, json={"decision": "confirm"})
    d = client.post(f"/api/billing/cases/{case['id']}/tracking", headers=BILLER,
                    json={"status": "resolved", "note": "Patient identity corrected with front office"}).json()
    s = statuses(d)
    assert d["state"] == "COMPLETED"
    assert s[4] == "blocked"
    assert [s[n] for n in (5, 6, 7)] == ["not_reached"] * 3
    assert s[8] == "done"


def test_escalated_case_needs_a_resolution_note(client):
    case = sync(client)["CLM-9005"]
    client.post(f"/api/billing/cases/{case['id']}/classification-review", headers=APPROVER, json={"decision": "confirm"})
    r = client.post(f"/api/billing/cases/{case['id']}/tracking", headers=BILLER, json={"status": "resolved"})
    assert r.status_code == 422


def test_resolving_case_closes_its_open_exceptions(client):
    case = sync(client)["CLM-9005"]
    client.post(f"/api/billing/cases/{case['id']}/classification-review", headers=APPROVER, json={"decision": "confirm"})
    open_before = [e for e in client.get("/api/exceptions?status=open", headers=ADMIN).json() if e["entity_id"] == case["id"]]
    assert open_before
    client.post(f"/api/billing/cases/{case['id']}/tracking", headers=BILLER, json={"status": "resolved", "note": "Fixed"})
    open_after = [e for e in client.get("/api/exceptions?status=open", headers=ADMIN).json() if e["entity_id"] == case["id"]]
    resolved = [e for e in client.get("/api/exceptions?status=resolved", headers=ADMIN).json() if e["entity_id"] == case["id"]]
    assert open_after == [] and len(resolved) == len(open_before)
    assert resolved[0]["resolved_by"] == "biller.test"


def test_hard_stop_is_shown_at_the_draft_step(client):
    case = sync(client)["CLM-9003"]
    d = client.post(f"/api/billing/cases/{case['id']}/classification-review", headers=BILLER, json={"decision": "confirm"}).json()
    s = statuses(d)
    assert [s[n] for n in (1, 2, 3, 4, 5)] == ["done"] * 5
    assert s[6] == "blocked" and s[7] == "not_reached"


def test_waiting_case_shows_human_gate(client):
    d = client.get(f"/api/billing/cases/{sync(client)['CLM-9001']['id']}", headers=BILLER).json()
    s = statuses(d)
    assert s[3] == "waiting_human" and s[4] == "pending"
