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

import httpx

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


class GeminiLLMClient(LLMClient):
    """Gemini via the Google GenAI SDK, using forced function calling for structured output.

    The free tier may use prompts to improve Google's products: synthetic data only. Production use
    with PHI requires a paid plan with appropriate agreements.
    """

    name = "gemini"

    def __init__(self, *, api_key: str, model: str, max_retries: int, timeout: float, max_tokens: int,
                 temperature: float | None = None, max_wait: float = 60.0):
        from google import genai  # imported lazily so the mock path has no hard dependency at import time
        from google.genai import errors, types

        self._types = types
        self._errors = errors
        # SDK retries are off by default; we own the retry policy so attempts are capped and logged.
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))
        self._model = model
        self._max_retries = max(1, max_retries)
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._max_wait = max_wait

    def _is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, (httpx.TransportError, self._errors.ServerError)):
            return True
        return isinstance(exc, self._errors.ClientError) and getattr(exc, "code", None) in (408, 429)

    def structured(self, *, task, system, user, tool_name, tool_description, schema,
                   prompt_version, context=None) -> LLMResult:
        t = self._types
        config = t.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self._max_tokens,
            temperature=self._temperature,
            tools=[t.Tool(function_declarations=[t.FunctionDeclaration(
                name=tool_name, description=tool_description, parameters_json_schema=schema)])],
            tool_config=t.ToolConfig(function_calling_config=t.FunctionCallingConfig(
                mode=t.FunctionCallingConfigMode.ANY, allowed_function_names=[tool_name])),
        )
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.models.generate_content(model=self._model, contents=user, config=config)
            except Exception as exc:
                if self._is_retryable(exc):
                    last_error = exc
                    log.warning("LLM %s attempt %s/%s failed: %s", task, attempt, self._max_retries, type(exc).__name__)
                    if attempt < self._max_retries:
                        time.sleep(self._retry_wait(exc, attempt))
                    continue
                if isinstance(exc, self._errors.APIError):  # 4xx etc.: not retryable
                    raise LLMError(f"Model request rejected ({getattr(exc, 'code', '?')})") from exc
                raise

            args = self._function_args(response, tool_name)
            usage = getattr(response, "usage_metadata", None)
            return LLMResult(
                data=args,
                model=getattr(response, "model_version", None) or self._model,
                prompt_version=prompt_version,
                input_tokens=getattr(usage, "prompt_token_count", None),
                output_tokens=getattr(usage, "candidates_token_count", None),
                attempts=attempt,
            )
        raise LLMError(f"Model unavailable after {self._max_retries} attempts: {type(last_error).__name__}")

    def _retry_wait(self, exc: Exception, attempt: int) -> float:
        """How long to wait before retrying. On 429, Gemini says how long (RetryInfo.retryDelay);
        honour it, capped, instead of guessing. Otherwise exponential backoff."""
        backoff = float(min(2 ** attempt, 8))
        if getattr(exc, "code", None) != 429:
            return backoff
        return min(max(parse_retry_delay(getattr(exc, "details", None)) or 0.0, 15.0 * attempt, backoff), self._max_wait)

    @staticmethod
    def _function_args(response, tool_name: str) -> dict:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            reason = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
            raise LLMError(f"Model returned no answer (blocked: {reason or 'unknown'})")
        candidate = candidates[0]
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        for part in parts:
            call = getattr(part, "function_call", None)
            if call is not None and call.name == tool_name and isinstance(call.args, dict):
                return dict(call.args)
        reason = getattr(candidate, "finish_reason", None)
        reason = getattr(reason, "name", reason)
        raise LLMError(f"Model did not return the required structured output (finish reason: {reason})")


def parse_retry_delay(details) -> float | None:
    """Extract seconds from a Google API error body: {"error": {"details": [{"@type": "...RetryInfo", "retryDelay": "12s"}]}}."""
    try:
        error = details.get("error", details) if isinstance(details, dict) else {}
        for d in error.get("details", []) or []:
            if str(d.get("@type", "")).endswith("RetryInfo") and d.get("retryDelay"):
                return float(str(d["retryDelay"]).rstrip("s"))
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def build_llm_client(settings: Settings) -> LLMClient:
    client = _build_provider(settings)
    if client.name != "mock" and settings.llm_requests_per_minute and settings.llm_requests_per_minute > 0:
        from app.llm.throttle import ThrottledLLMClient
        log.info("Model calls throttled to %s per minute", settings.llm_requests_per_minute)
        return ThrottledLLMClient(client, settings.llm_requests_per_minute)
    return client


def _build_provider(settings: Settings) -> LLMClient:
    from app.llm.mock import MockLLMClient

    provider = settings.llm_provider.lower()
    explicit = "llm_provider" in settings.model_fields_set
    if provider == "mock":
        return MockLLMClient()
    if provider == "gemini":
        if not settings.gemini_api_key:
            if explicit:
                raise ConfigurationError("VM_LLM_PROVIDER=gemini requires GEMINI_API_KEY")
            log.warning("GEMINI_API_KEY not set: using the offline mock LLM")
            return MockLLMClient()
        return GeminiLLMClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout_seconds,
            max_tokens=settings.gemini_max_tokens,
            temperature=settings.gemini_temperature,
            max_wait=settings.llm_max_retry_wait_seconds,
        )
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ConfigurationError("VM_LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
        )
    raise ConfigurationError(f"Unknown VM_LLM_PROVIDER '{settings.llm_provider}' (use gemini, anthropic or mock)")
