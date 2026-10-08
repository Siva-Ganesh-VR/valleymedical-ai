"""Exercises GeminiLLMClient's parsing and retry policy without network access."""
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.config import Settings
from app.errors import ConfigurationError
from app.llm import client as client_module
from app.llm.client import GeminiLLMClient, LLMError, build_llm_client
from app.llm.mock import MockLLMClient


def make(responses):
    c = GeminiLLMClient(api_key="test-key", model="gemini-test", max_retries=3, timeout=5, max_tokens=256)
    calls = {"n": 0, "config": None}

    def generate_content(**kwargs):
        calls["config"] = kwargs["config"]
        r = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(r, Exception):
            raise r
        return r

    c._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return c, calls


def call_response(data, name="submit"):
    part = SimpleNamespace(function_call=SimpleNamespace(name=name, args=data))
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")],
                           model_version="gemini-test-001",
                           usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5))


ARGS = dict(task="t", system="s", user="u", tool_name="submit", tool_description="d",
            schema={"type": "object"}, prompt_version="v1")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)


def api_error(cls, code):
    return cls(code, {"error": {"message": "x", "status": "X"}})


def test_forces_function_call_and_returns_args():
    c, calls = make([call_response({"ok": True})])
    result = c.structured(**ARGS)
    assert result.data == {"ok": True} and result.input_tokens == 10 and result.model == "gemini-test-001"
    fcc = calls["config"].tool_config.function_calling_config
    assert fcc.mode.value == "ANY" and fcc.allowed_function_names == ["submit"]
    assert calls["config"].max_output_tokens == 256


@pytest.mark.parametrize("exc", [
    api_error(errors.ServerError, 503),
    api_error(errors.ClientError, 429),
    httpx.ConnectError("down"),
])
def test_retries_transient_errors_then_succeeds(exc):
    c, calls = make([exc, call_response({"ok": 1})])
    assert c.structured(**ARGS).attempts == 2 and calls["n"] == 2


def test_gives_up_after_capped_attempts():
    c, calls = make([api_error(errors.ServerError, 500)])
    with pytest.raises(LLMError):
        c.structured(**ARGS)
    assert calls["n"] == 3


def test_client_errors_are_not_retried():
    c, calls = make([api_error(errors.ClientError, 400)])
    with pytest.raises(LLMError, match="400"):
        c.structured(**ARGS)
    assert calls["n"] == 1


def test_blocked_prompt_is_an_error():
    c, _ = make([SimpleNamespace(candidates=[], prompt_feedback=SimpleNamespace(block_reason="SAFETY"))])
    with pytest.raises(LLMError, match="blocked"):
        c.structured(**ARGS)


def test_truncated_or_text_only_output_is_an_error():
    truncated = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]), finish_reason="MAX_TOKENS")])
    c, _ = make([truncated])
    with pytest.raises(LLMError, match="MAX_TOKENS"):
        c.structured(**ARGS)


def test_wrong_function_name_is_an_error():
    c, _ = make([call_response({"ok": True}, name="other")])
    with pytest.raises(LLMError):
        c.structured(**ARGS)


def settings(**kw):
    return Settings(_env_file=None, **{"gemini_api_key": None, "anthropic_api_key": None, **kw})


def test_default_provider_without_key_falls_back_to_mock():
    assert isinstance(build_llm_client(settings()), MockLLMClient)


def test_explicit_provider_without_key_fails():
    for p in ("gemini", "anthropic"):
        with pytest.raises(ConfigurationError):
            build_llm_client(settings(llm_provider=p))


def test_provider_switch_builds_each_client():
    assert build_llm_client(settings(gemini_api_key="k")).name == "gemini"
    assert build_llm_client(settings(llm_provider="anthropic", anthropic_api_key="k")).name == "anthropic"
    assert build_llm_client(settings(llm_provider="mock")).name == MockLLMClient().name


def test_unknown_provider_fails():
    with pytest.raises(ConfigurationError):
        build_llm_client(settings(llm_provider="auto"))
