"""Single-service hosting: password protection and serving the UI."""
import base64
from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.llm.mock import MockLLMClient
from app.main import create_app
from tests.conftest import BILLER


def app_with(tmp_path=None, password=None):
    static = None
    if tmp_path is not None:
        static = tmp_path / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<html>UI</html>")
        (static / "assets" / "app.js").write_text("console.log(1)")
    s = Settings(database_url="sqlite:///:memory:", llm_provider="mock", as_of_date=date(2026, 9, 1),
                 static_dir=static, demo_password=password)
    return TestClient(create_app(build_container(s, llm=MockLLMClient())))


def basic(pw, user="demo"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def test_password_protects_ui_and_api(tmp_path):
    client = app_with(tmp_path, password="s3cret-demo")
    assert client.get("/").status_code == 401
    assert client.get("/").headers["www-authenticate"].startswith("Basic")
    assert client.get("/api/billing/cases", headers=BILLER).status_code == 401
    assert client.get("/", headers=basic("wrong")).status_code == 401
    assert client.get("/", headers=basic("s3cret-demo", user="anyone")).status_code == 200
    assert client.get("/api/billing/cases", headers=BILLER | basic("s3cret-demo")).status_code == 200


def test_health_check_stays_open_for_the_host(tmp_path):
    client = app_with(tmp_path, password="s3cret-demo")
    assert client.get("/api/health").status_code == 200


def test_ui_is_served_with_client_side_routes(tmp_path):
    client = app_with(tmp_path)
    assert "UI" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "UI" in client.get("/billing/cases/abc").text  # deep link falls back to index.html
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_nothing_changes_when_not_configured():
    client = app_with()
    assert client.get("/api/billing/cases", headers=BILLER).status_code == 200
    assert client.get("/").status_code == 404
