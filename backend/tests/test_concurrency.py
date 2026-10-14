"""Regression for 'database is locked' on Render: a slow batch must not block other users."""
import threading
import time
from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.llm.mock import MockLLMClient
from app.main import create_app
from tests.conftest import APPROVER, BILLER, PROVIDER

CALL_SECONDS = 0.15


class SlowLLM(MockLLMClient):
    """Stands in for a live model plus rate-limit spacing."""

    def structured(self, **kw):
        time.sleep(CALL_SECONDS)
        return super().structured(**kw)


def file_app(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path / 'poc.db'}", llm_provider="mock", as_of_date=date(2026, 9, 1))
    return create_app(build_container(s, llm=SlowLLM()))


def test_other_users_can_write_while_a_batch_runs(tmp_path):
    app = file_app(tmp_path)
    batch, other = TestClient(app), TestClient(app)
    result = {}

    def run_batch():
        result["sync"] = batch.post("/api/billing/queues/denials-team-a/sync", headers=BILLER)

    t = threading.Thread(target=run_batch)
    t.start()
    time.sleep(1.0)  # batch is now in the middle of its model calls
    started = time.perf_counter()
    r = other.get("/api/patients/SYN-P-0001/record", headers=PROVIDER)  # writes an audit entry
    waited = time.perf_counter() - started
    t.join()

    assert r.status_code == 200, r.text
    assert waited < 1.5, f"second user waited {waited:.1f}s for the database lock"
    assert result["sync"].status_code == 200
    assert result["sync"].json()["created"] == 27


def test_second_batch_on_same_queue_gets_a_clear_message(tmp_path):
    app = file_app(tmp_path)
    first, second = TestClient(app), TestClient(app)
    t = threading.Thread(target=lambda: first.post("/api/billing/queues/denials-team-a/sync", headers=BILLER))
    t.start()
    time.sleep(0.5)
    r = second.post("/api/billing/queues/denials-team-a/demo-workload", headers=APPROVER)
    t.join()
    assert r.status_code == 409
    assert "Read work queue" in r.json()["message"] and "still running" in r.json()["message"]
    # Once the first batch is done, the second one works.
    assert second.post("/api/billing/queues/denials-team-a/demo-workload", headers=APPROVER).status_code == 200
