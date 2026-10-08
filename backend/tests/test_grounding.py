from app.services.grounding import check_draft, check_statement

EVIDENCE = {
    "E1": "Gabapentin 300 mg three times daily (active, started 2025-11-03)",
    "E2": "Pain score 5/10 (NRS 0-10) on 2026-05-14",
}


def test_supported_statement_passes():
    assert check_statement("Takes gabapentin 300 mg three times daily.", ["E1"], EVIDENCE) == []


def test_statement_without_citation_fails():
    assert check_statement("Takes gabapentin.", [], EVIDENCE) == ["No source cited"]


def test_unknown_citation_fails():
    assert any("unknown source" in r for r in check_statement("Pain 5/10.", ["E9"], EVIDENCE))


def test_wrong_number_fails():
    reasons = check_statement("Takes gabapentin 600 mg.", ["E1"], EVIDENCE)
    assert any("600" in r for r in reasons)


def test_drug_not_in_cited_source_fails():
    reasons = check_statement("Takes oxycodone 300 mg.", ["E1"], EVIDENCE)
    assert any("oxycodone" in r for r in reasons)


def test_number_from_other_source_fails():
    # 5 is in E2, but the statement only cites E1.
    assert check_statement("Pain is 5/10.", ["E1"], EVIDENCE)


def test_draft_claiming_submission_is_blocked():
    errors, _ = check_draft("This appeal has been submitted to the payer.", [], EVIDENCE, "CLM-1")
    assert errors


def test_draft_with_unknown_inline_citation_is_blocked():
    errors, _ = check_draft("Records show improvement [E7].", [], EVIDENCE, "CLM-1")
    assert any("E7" in e for e in errors)


def test_draft_with_unexplained_number_gets_warning_not_error():
    errors, warnings = check_draft("Please process within 45 days.", [], EVIDENCE, "CLM-1")
    assert not errors and warnings
