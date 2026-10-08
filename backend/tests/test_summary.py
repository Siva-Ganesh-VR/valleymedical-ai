from app.llm.client import LLMClient, LLMResult
from app.llm.mock import FailingLLMClient
from tests.conftest import PROVIDER, make_client


class FabricatingLLM(LLMClient):
    name = "fabricating"

    def structured(self, **kwargs):
        return LLMResult(data={"statements": [
            {"section": "medications", "text": "Current medication: Gabapentin 300 mg three times daily.", "evidence_ids": ["E4"]},
            {"section": "medications", "text": "Takes oxycodone 10 mg daily.", "evidence_ids": ["E4"]},
            {"section": "history", "text": "Has a history of diabetes.", "evidence_ids": []},
        ]}, model="stub", prompt_version="test")


def test_mock_summary_statements_are_all_cited(client):
    body = client.post("/api/patients/SYN-P-0001/previsit-summary", headers=PROVIDER).json()
    assert body["status"] == "ok" and body["statements"]
    assert all(s["citations"] for s in body["statements"])
    assert [a["data"]["substance"] for a in body["verified_allergies"]] == ["Penicillin"]


def test_fabricated_and_uncited_statements_are_removed():
    _, client = make_client(llm=FabricatingLLM())
    body = client.post("/api/patients/SYN-P-0001/previsit-summary", headers=PROVIDER).json()
    kept = [s["text"] for s in body["statements"]]
    removed = [r["text"] for r in body["removed"]]
    assert "Takes oxycodone 10 mg daily." in removed
    assert "Has a history of diabetes." in removed
    assert all("oxycodone" not in t for t in kept)


def test_summary_reports_data_gaps():
    _, client = make_client()
    body = client.post("/api/patients/SYN-P-0004/previsit-summary", headers=PROVIDER).json()
    assert any("Labs could not be loaded" in g for g in body["data_gaps"])
    assert any("withheld" in g for g in body["data_gaps"])


def test_model_failure_degrades_safely():
    _, client = make_client(llm=FailingLLMClient())
    body = client.post("/api/patients/SYN-P-0001/previsit-summary", headers=PROVIDER).json()
    assert body["status"] == "failed" and body["statements"] == []
    assert body["verified_medications"]  # structured lists still shown
