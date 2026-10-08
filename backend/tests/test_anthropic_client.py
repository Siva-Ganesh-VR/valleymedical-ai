"""Exercises AnthropicLLMClient's parsing and retry policy without network access."""
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.llm import client as client_module
from app.llm.client import AnthropicLLMClient, LLMError


def make(responses):
    c = AnthropicLLMClient(api_key="test-key", model="claude-sonnet-5-5", max_retries=3, timeout=5, max_tokens=256)
    calls = {"n": 0, "kwargs": None}

    def create(**kwargs):
        calls["kwargs"] = kwargs
        r = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(r, Exception):
            raise r
        return r

    c._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return c, calls


def tool_response(data):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=data)], model="claude-sonnet-5-5",
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


ARGS = dict(task="t", system="s", user="u", tool_name="submit", tool_description="d",
            schema={"type": "object"}, prompt_version="v1")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)


def connection_error():
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def test_forces_tool_use_and_returns_tool_input():
    c, calls = make([tool_response({"ok": True})])
    result = c.structured(**ARGS)
    assert result.data == {"ok": True} and result.input_tokens == 10
    assert calls["kwargs"]["tool_choice"] == {"type": "tool", "name": "submit"}


def test_retries_transient_errors_then_succeeds():
    c, calls = make([connection_error(), tool_response({"ok": 1})])
    assert c.structured(**ARGS).attempts == 2 and calls["n"] == 2


def test_gives_up_after_capped_attempts():
    c, calls = make([connection_error()])
    with pytest.raises(LLMError):
        c.structured(**ARGS)
    assert calls["n"] == 3


def test_missing_tool_output_is_an_error():
    c, _ = make([SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")], model="m", usage=None)])
    with pytest.raises(LLMError):
        c.structured(**ARGS)
