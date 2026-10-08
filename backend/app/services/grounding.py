"""Deterministic checks that generated text is grounded in its sources.

These checks do not prove correctness. They catch the most dangerous failure modes cheaply:
citations to non-existent sources, numbers that appear nowhere in the cited sources, and
medication or allergy names that are not in the cited sources. Clinician review remains
the final control.
"""
from __future__ import annotations

import re

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Small illustrative lexicon of drug and allergen names. Production should use a maintained
# terminology (e.g. RxNorm) and the patient's own medication and allergy lists.
DRUG_LEXICON = {
    "acetaminophen", "amitriptyline", "aspirin", "baclofen", "buprenorphine", "celecoxib", "codeine",
    "cyclobenzaprine", "diclofenac", "duloxetine", "fentanyl", "gabapentin", "hydrocodone", "ibuprofen",
    "lidocaine", "lisinopril", "meloxicam", "metformin", "methadone", "morphine", "naloxone", "naproxen",
    "oxycodone", "penicillin", "prednisone", "pregabalin", "sertraline", "sulfa", "tizanidine", "tramadol",
    "warfarin",
}


def _numbers(text: str) -> set[str]:
    out = set()
    for n in NUMBER_RE.findall(text):
        out.add(n)
        try:
            f = float(n)
            out.add(str(int(f)) if f.is_integer() else f"{f:g}")
        except ValueError:
            pass
    return out


def _terms(text: str, vocabulary: set[str]) -> set[str]:
    lowered = text.casefold()
    return {t for t in vocabulary if re.search(rf"\b{re.escape(t)}\b", lowered)}


def check_statement(text: str, cited_ids: list[str], evidence: dict[str, str], extra_terms: set[str] | None = None) -> list[str]:
    """Return reasons the statement is NOT supported. Empty list means it passed."""
    reasons: list[str] = []
    if not cited_ids:
        return ["No source cited"]
    unknown = [i for i in cited_ids if i not in evidence]
    if unknown:
        reasons.append(f"Cites unknown source(s): {', '.join(unknown)}")
    corpus = " ".join(evidence[i] for i in cited_ids if i in evidence)
    missing_numbers = sorted(_numbers(text) - _numbers(corpus), key=str)
    if missing_numbers:
        reasons.append(f"Number(s) not found in cited source: {', '.join(missing_numbers)}")
    vocabulary = DRUG_LEXICON | {t.casefold() for t in (extra_terms or set())}
    missing_terms = sorted(_terms(text, vocabulary) - _terms(corpus, vocabulary))
    if missing_terms:
        reasons.append(f"Mentions {', '.join(missing_terms)} not found in cited source")
    return reasons


# A draft must never claim that IT (or the appeal it represents) has already gone out.
SUBMISSION_CLAIMS = re.compile(
    r"\b(this|the|our)\s+(appeal|letter|query|request|draft|inquiry)\s+(has been|was|is being)\s+"
    r"(submitted|sent|filed|faxed|transmitted)\b",
    re.I,
)


def check_draft(text: str, cited_ids: list[str], evidence: dict[str, str], claim_text: str) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for a billing draft. Errors block the draft; warnings are shown to the approver."""
    errors: list[str] = []
    warnings: list[str] = []
    if not text.strip():
        errors.append("Draft is empty")
    unknown = [i for i in cited_ids if i not in evidence]
    inline = set(re.findall(r"\[(E\d+)\]", text))
    unknown += [i for i in inline if i not in evidence and i not in unknown]
    if unknown:
        errors.append(f"Cites unknown source(s): {', '.join(sorted(unknown))}")
    corpus = claim_text + " " + " ".join(evidence.values())
    bad_terms = sorted(_terms(text, DRUG_LEXICON) - _terms(corpus, DRUG_LEXICON))
    if bad_terms:
        errors.append(f"Mentions {', '.join(bad_terms)}, which is not in the claim or retrieved records")
    if SUBMISSION_CLAIMS.search(text):
        errors.append("Draft claims something was submitted or sent; drafts must not")
    missing_numbers = sorted(_numbers(text) - _numbers(corpus), key=str)
    if missing_numbers:
        warnings.append(f"Check these numbers; they are not in the claim or records: {', '.join(missing_numbers)}")
    return errors, warnings
