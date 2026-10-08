from app.audit import verify_chain
from app.models import AuditEvent
from tests.conftest import ADMIN, BILLER, PROVIDER, sync


def test_requests_without_identity_are_rejected(client):
    assert client.get("/api/patients").status_code == 401


def test_system_role_cannot_be_impersonated(client):
    assert client.get("/api/patients", headers={"X-Demo-User": "x", "X-Demo-Role": "system"}).status_code == 401


def test_billing_staff_cannot_browse_clinical_records(client):
    assert client.get("/api/patients/SYN-P-0001/record", headers=BILLER).status_code == 403


def test_providers_cannot_open_billing(client):
    assert client.get("/api/billing/cases", headers=PROVIDER).status_code == 403


def test_only_admin_reads_audit(client):
    assert client.get("/api/audit", headers=PROVIDER).status_code == 403
    assert client.get("/api/audit", headers=ADMIN).status_code == 200


def test_audit_chain_verifies_and_detects_tampering(container, client):
    sync(client)
    client.get("/api/patients/SYN-P-0001/record", headers=PROVIDER)
    assert client.get("/api/audit/verify", headers=ADMIN).json()["ok"] is True

    s = container.sessionmaker()
    row = s.query(AuditEvent).order_by(AuditEvent.id).offset(2).first()
    row.actor = "someone-else"
    s.commit()
    result = verify_chain(s)
    assert result.ok is False and result.first_invalid_id == row.id


def test_errors_do_not_leak_internals(client):
    r = client.get("/api/billing/cases/does-not-exist", headers=BILLER)
    assert r.status_code == 404 and r.json()["error"] == "not_found"
