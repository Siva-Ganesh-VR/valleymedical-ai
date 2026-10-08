from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.llm.mock import MockLLMClient
from app.main import create_app

PROVIDER = {"X-Demo-User": "dr.test", "X-Demo-Role": "provider"}
BILLER = {"X-Demo-User": "biller.test", "X-Demo-Role": "biller"}
APPROVER = {"X-Demo-User": "approver.test", "X-Demo-Role": "billing_approver"}
ADMIN = {"X-Demo-User": "admin.test", "X-Demo-Role": "admin"}


def make_container(llm=None, **kwargs):
    settings = Settings(database_url="sqlite:///:memory:", llm_provider="mock", as_of_date=date(2026, 9, 1))
    return build_container(settings, llm=llm or MockLLMClient(), **kwargs)


@pytest.fixture
def container():
    return make_container()


@pytest.fixture
def client(container):
    return TestClient(create_app(container))


@pytest.fixture
def session(container):
    s = container.sessionmaker()
    yield s
    s.close()


def make_client(**kwargs):
    c = make_container(**kwargs)
    return c, TestClient(create_app(c))


def sync(client):
    r = client.post("/api/billing/queues/denials-team-a/sync", headers=BILLER)
    assert r.status_code == 200, r.text
    return {c["claim_id"]: c for c in client.get("/api/billing/cases", headers=BILLER).json()}
