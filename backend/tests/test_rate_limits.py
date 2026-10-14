"""Rate limits (429) from the model provider: throttling, retry delays and recovery."""
from types import SimpleNamespace

from app.llm.client import LLMError, parse_retry_delay
from app.llm.mock import MockLLMClient
from app.llm.throttle import RateLimiter
from tests.conftest import ADMIN, APPROVER, BILLER, make_client, sync


class FlakyLLM(MockLLMClient):
    """Behaves like a key that hits its quota: drafting fails while `limited` is True."""

    limited = False

    def structured(self, *, task, **kw):
        if self.limited and task == "billing_draft":
            raise LLMError("Model unavailable after 3 attempts: ClientError")
        return super().structured(task=task, **kw)


def test_rate_limiter_spaces_calls():
    now = [0.0]
    waits = []

    def sleep(sec):
        waits.append(sec)
        now[0] += sec

    limiter = RateLimiter(3, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        assert limiter.acquire() == 0
    assert limiter.acquire() > 59  # 4th call in the same minute waits for a slot
    assert len(waits) == 1


def test_retry_delay_is_read_from_gemini_error():
    body = {"error": {"code": 429, "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "23s"}]}}
    assert parse_retry_delay(body) == 23.0
    assert parse_retry_delay({"error": {}}) is None
    assert parse_retry_delay(None) is None


def test_gemini_client_waits_as_long_as_asked():
    from app.llm.client import GeminiLLMClient

    client = GeminiLLMClient.__new__(GeminiLLMClient)
    client._max_wait = 60.0
    err = SimpleNamespace(code=429, details={"error": {"details": [{"@type": "x.RetryInfo", "retryDelay": "41s"}]}})
    assert client._retry_wait(err, 1) == 41.0
    assert client._retry_wait(SimpleNamespace(code=429, details={"error": {"details": [{"@type": "x.RetryInfo", "retryDelay": "300s"}]}}), 1) == 60.0
    assert client._retry_wait(SimpleNamespace(code=503, details=None), 1) == 2.0


def test_real_providers_are_throttled_and_mock_is_not():
    from app.config import Settings
    from app.llm.client import build_llm_client
    from app.llm.throttle import ThrottledLLMClient

    assert not isinstance(build_llm_client(Settings(llm_provider="mock")), ThrottledLLMClient)
    gem = build_llm_client(Settings(llm_provider="gemini", gemini_api_key="test-key", llm_requests_per_minute=8))
    assert isinstance(gem, ThrottledLLMClient) and gem.per_minute == 8 and gem.name == "gemini"
    off = build_llm_client(Settings(llm_provider="gemini", gemini_api_key="test-key", llm_requests_per_minute=0))
    assert not isinstance(off, ThrottledLLMClient)


def _seed_with_quota_failure():
    llm = FlakyLLM()
    container, client = make_client(llm=llm)
    sync(client)
    llm.limited = True  # quota runs out just as the demo workload starts drafting
    client.post("/api/billing/queues/denials-team-a/demo-workload", headers=APPROVER)
    llm.limited = False  # quota is back a minute later
    return container, client


def test_bulk_retry_recovers_cases_stopped_by_rate_limit():
    _, client = _seed_with_quota_failure()
    cases = {c["claim_id"]: c for c in client.get("/api/billing/cases", headers=BILLER).json()}
    failed = [k for k, c in cases.items() if c["escalation_kind"] == "llm_failure"]
    assert failed, "the simulated quota failure should have escalated some cases"

    r = client.post("/api/billing/queues/denials-team-a/retry-ai", headers=BILLER).json()
    assert sorted(r["retried"]) == sorted(failed) and r["still_failing"] == []
    after = {c["claim_id"]: c for c in client.get("/api/billing/cases", headers=BILLER).json()}
    for claim in failed:
        assert after[claim]["state"] == "AWAITING_DRAFT_APPROVAL", claim
        assert after[claim]["escalation_kind"] is None
    # Intentional hard stops are untouched.
    assert after["CLM-9016"]["state"] == "ESCALATED" and after["CLM-9016"]["escalation_kind"] == "hard_stop_rule"
    open_llm = [e for e in client.get("/api/exceptions?status=open", headers=ADMIN).json() if e["kind"] == "llm_failure"]
    assert open_llm == []


def test_recovered_case_does_not_show_a_stopped_step():
    _, client = _seed_with_quota_failure()
    case = next(c for c in client.get("/api/billing/cases", headers=BILLER).json() if c["escalation_kind"] == "llm_failure")
    d = client.post(f"/api/billing/cases/{case['id']}/retry-ai", headers=BILLER).json()
    statuses = {s["step"]: s["status"] for s in d["steps"]}
    assert d["state"] == "AWAITING_DRAFT_APPROVAL"
    assert "blocked" not in statuses.values() and statuses[6] == "waiting_human"


def test_safety_escalations_cannot_be_retried(client):
    cid = sync(client)["CLM-9005"]["id"]  # patient mismatch
    client.post(f"/api/billing/cases/{cid}/classification-review", headers=BILLER, json={"decision": "confirm"})
    r = client.post(f"/api/billing/cases/{cid}/retry-ai", headers=BILLER)
    assert r.status_code == 409 and "needs a person" in r.json()["message"]


def test_retry_needs_billing_role(client):
    assert client.post("/api/billing/queues/denials-team-a/retry-ai", headers=ADMIN).status_code == 403
