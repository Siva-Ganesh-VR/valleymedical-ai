"""LLM client abstraction.

All model calls go through LLMClient.structured(), which forces the model to answer via a
single tool call whose input matches a JSON schema. Callers get parsed data plus the model
name and prompt version, which are written to the audit log.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import Settings
from app.errors import ConfigurationError

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model could not produce a usable answer (after any retries)."""


@dataclass
class LLMResult:
    data: dict
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    attempts: int = 1
    meta: dict = field(default_factory=dict)


class LLMClient(ABC):
    name: str = "abstract"

    @abstractmethod
    def structured(
        self,
        *,
        task: str,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        schema: dict,
        prompt_version: str,
        context: dict | None = None,
    ) -> LLMResult:
        """Return the tool input produced by the model.

        `context` is the same information as `user`, in structured form. Real clients ignore
        it; the offline mock uses it to produce deterministic output.
        """


class AnthropicLLMClient(LLMClient):
    """Claude via the Anthropic Messages API, using forced tool use for structured output.

    Production use with PHI requires a BAA with the model provider and approved
    data-retention terms. Do not send real PHI from a POC environment.
    """

    name = "anthropic"

    def __init__(self, *, api_key: str, model: str, max_retries: int, timeout: float, max_tokens: int):
        import anthropic  # imported lazily so the mock path has no hard dependency at import time

        self._anthropic = anthropic
        # SDK retries disabled: we own the retry policy so attempts are capped and logged.
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=timeout)
        self._model = model
        self._max_retries = max(1, max_retries)
        self._max_tokens = max_tokens

    def structured(self, *, task, system, user, tool_name, tool_description, schema,
                   prompt_version, context=None) -> LLMResult:
        a = self._anthropic
        retryable = (a.APIConnectionError, a.APITimeoutError, a.RateLimitError, a.InternalServerError)
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    tools=[{"name": tool_name, "description": tool_description, "input_schema": schema}],
                    tool_choice={"type": "tool", "name": tool_name},
                )
            except retryable as exc:
                last_error = exc
                log.warning("LLM %s attempt %s/%s failed: %s", task, attempt, self._max_retries, type(exc).__name__)
                if attempt < self._max_retries:
                    time.sleep(min(2 ** attempt, 8))
                continue
            except a.APIStatusError as exc:  # 4xx etc.: not retryable
                raise LLMError(f"Model request rejected ({exc.status_code})") from exc

            block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
            if block is None or not isinstance(block.input, dict):
                raise LLMError("Model did not return the required structured output")
            usage = getattr(response, "usage", None)
            return LLMResult(
                data=block.input,
                model=getattr(response, "model", self._model),
                prompt_version=prompt_version,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                attempts=attempt,
            )
        raise LLMError(f"Model unavailable after {self._max_retries} attempts: {type(last_error).__name__}")


def build_llm_client(settings: Settings) -> LLMClient:
    from app.llm.mock import MockLLMClient

    provider = settings.llm_provider.lower()
    if provider == "mock" or (provider == "auto" and not settings.anthropic_api_key):
        if provider == "auto":
            log.warning("ANTHROPIC_API_KEY not set: using the offline mock LLM")
        return MockLLMClient()
    if provider in ("anthropic", "auto"):
        if not settings.anthropic_api_key:
            raise ConfigurationError("VM_LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
        )
    raise ConfigurationError(f"Unknown VM_LLM_PROVIDER '{settings.llm_provider}'")
