from app.adapters.meditab.mock import MockMeditabAdapter
from app.config import Settings
from app.security import Actor, Role
from app.services.exceptions import ExceptionService

from tests.conftest import make_container

DOCTOR = Actor("dr.test", Role.PROVIDER)


def test_unavailable_section_is_reported_not_silently_empty(container, session):
    record = container.records(session).get_record("SYN-P-0004", actor=DOCTOR, purpose="test")
    labs = next(s for s in record.statuses if s.section == "labs")
    assert labs.status == "unavailable" and labs.item_count == 0


def test_mismatched_document_is_quarantined_and_raised(container, session):
    record = container.records(session).get_record("SYN-P-0004", actor=DOCTOR, purpose="test")
    assert [q.document_id for q in record.quarantined] == ["DOC-4001"]
    assert all("DOC-4001" not in i.item_id for i in record.items["documents"])
    kinds = [e.kind for e in container.exceptions(session).list("open")]
    assert "document_identity_mismatch" in kinds


def test_every_item_carries_a_source_for_the_right_patient(container, session):
    record = container.records(session).get_record("SYN-P-0001", actor=DOCTOR, purpose="test")
    items = record.all_items()
    assert items
    for item in items:
        assert item.source.system == "meditab" and item.source.record_id
        assert item.date is not None
    pages = [i for i in record.items["documents"] if i.source.record_id == "DOC-2001"]
    assert sorted(i.source.page for i in pages) == [1, 2]


class LeakyAdapter(MockMeditabAdapter):
    """Simulates an integration bug that returns another patient's medication."""

    def list_medications(self, patient_id):
        return super().list_medications(patient_id) + super().list_medications("SYN-P-0002")


def test_cross_patient_items_are_withheld():
    leaky = LeakyAdapter.from_file(Settings().meditab_fixture)
    c = make_container(meditab=leaky)
    s = c.sessionmaker()
    record = c.records(s).get_record("SYN-P-0001", actor=DOCTOR, purpose="test")
    assert all("MED-0004" not in i.item_id for i in record.items["medications"])
    critical = [e for e in ExceptionService(s, c.audit(s)).list("open") if e.kind == "cross_patient_item"]
    assert critical and critical[0].severity == "critical"


def test_record_read_is_audited_with_purpose(client):
    from tests.conftest import ADMIN, PROVIDER

    client.get("/api/patients/SYN-P-0001/record", headers=PROVIDER)
    rows = client.get("/api/audit", headers=ADMIN).json()
    read = next(r for r in rows if r["action"] == "clinical_record.read")
    assert read["purpose"] == "chart_review" and read["actor"] == "dr.test" and read["patient_ref"] == "SYN-P-0001"
