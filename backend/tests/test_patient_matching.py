from datetime import date

from app.adapters.meditab.mock import MockMeditabAdapter
from app.config import Settings
from app.services.patient_matching import MatchStatus, PatientMatcher


def matcher():
    return PatientMatcher(MockMeditabAdapter.from_file(Settings().meditab_fixture))


def test_internal_id_matches():
    r = matcher().match(patient_id="SYN-P-0001")
    assert r.status == MatchStatus.MATCHED and r.patient.mrn == "SYN100001"


def test_mrn_with_agreeing_demographics_is_verified():
    r = matcher().match(mrn="SYN100001", last_name="testpatient", dob=date(1971, 4, 12))
    assert r.matched and r.verified


def test_mrn_with_wrong_dob_is_conflict_and_returns_no_patient():
    r = matcher().match(mrn="SYN100002", last_name="Samplecase", dob=date(1984, 10, 30))
    assert r.status == MatchStatus.CONFLICT
    assert r.patient is None


def test_demographics_shared_by_two_patients_is_ambiguous():
    r = matcher().match(last_name="Samplecase", first_name="Jordan", dob=date(1984, 9, 30))
    assert r.status == MatchStatus.AMBIGUOUS and len(r.candidate_ids) == 2


def test_demographics_only_never_auto_matches():
    r = matcher().match(last_name="Testpatient", dob=date(1971, 4, 12))
    assert r.status == MatchStatus.UNCONFIRMED and r.patient is None


def test_unknown_mrn_is_no_match():
    assert matcher().match(mrn="SYN999999").status == MatchStatus.NO_MATCH


def test_document_with_foreign_identifiers_is_conflict():
    m = matcher()
    adapter = MockMeditabAdapter.from_file(Settings().meditab_fixture)
    patient = adapter.get_patient("SYN-P-0004")
    doc = next(d for d in adapter.list_documents("SYN-P-0004") if d.document_id == "DOC-4001")
    assert m.verify_document(patient, doc).status == MatchStatus.CONFLICT
