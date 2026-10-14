"""AI gateway (WBS N3, N10): the single path for every model call.

Wraps any LLMClient (Gemini, Claude, mock) and, per call:
- refuses when an administrator has paused AI, or the monthly token budget is used up;
- records task, model, prompt version, tokens, latency and estimated cost in `llm_calls`.

A refused call raises AIPausedError (a subclass of LLMError), so every existing failure path
applies: billing cases escalate to the exception queue and summaries degrade safely.
The gateway writes through the caller's session, so it never contends for a SQLite lock.
"""
from __future__ import annotations

import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.llm.client import LLMClient, LLMError, LLMResult
from app.models import ControlFlag, LLMCall, utcnow_iso
from app.security import Actor

PAUSE_FLAG = "ai_paused"


class AIPausedError(LLMError):
    """AI calls are blocked by policy (kill switch or budget)."""


def month_prefix(ts: str | None = None) -> str:
    return (ts or utcnow_iso())[:7]


def tokens_used_this_month(session: Session) -> int:
    total = session.scalar(
        select(func.coalesce(func.sum(LLMCall.input_tokens + LLMCall.output_tokens), 0))
        .where(LLMCall.ts.like(f"{month_prefix()}%"), LLMCall.status == "ok")
    )
    return int(total or 0)


def pause_state(session: Session) -> dict:
    flag = session.get(ControlFlag, PAUSE_FLAG)
    return dict(flag.value) | {"updated_by": flag.updated_by, "updated_at": flag.updated_at} if flag else {"paused": False}


def set_paused(session: Session, actor: Actor, paused: bool, reason: str | None) -> dict:
    flag = session.get(ControlFlag, PAUSE_FLAG)
    value = {"paused": paused, "reason": reason}
    if flag is None:
        session.add(ControlFlag(key=PAUSE_FLAG, value=value, updated_by=actor.username, updated_at=utcnow_iso()))
    else:
        flag.value, flag.updated_by, flag.updated_at = value, actor.username, utcnow_iso()
    session.flush()
    return pause_state(session)


def estimate_cost(settings: Settings, input_tokens: int, output_tokens: int) -> float | None:
    if settings.llm_price_input_per_mtok is None or settings.llm_price_output_per_mtok is None:
        return None
    return round(input_tokens / 1e6 * settings.llm_price_input_per_mtok
                 + output_tokens / 1e6 * settings.llm_price_output_per_mtok, 6)


class LLMGateway(LLMClient):
    def __init__(self, inner: LLMClient, session: Session, settings: Settings):
        self._inner = inner
        self._s = session
        self._settings = settings
        self.name = inner.name

    @property
    def inner(self) -> LLMClient:
        return self._inner

    def check_allowed(self) -> None:
        state = pause_state(self._s)
        if state.get("paused"):
            raise AIPausedError("AI is paused by an administrator" + (f": {state['reason']}" if state.get("reason") else ""))
        budget = self._settings.llm_monthly_token_budget
        if budget and tokens_used_this_month(self._s) >= budget:
            raise AIPausedError(f"Monthly AI token budget ({budget:,}) is used up")

    def structured(self, *, task, system, user, tool_name, tool_description, schema,
                   prompt_version, context=None) -> LLMResult:
        try:
            self.check_allowed()
        except AIPausedError as exc:
            self._record(task, prompt_version, "blocked", note=str(exc))
            raise
        started = time.perf_counter()
        try:
            result = self._inner.structured(task=task, system=system, user=user, tool_name=tool_name,
                                            tool_description=tool_description, schema=schema,
                                            prompt_version=prompt_version, context=context)
        except LLMError as exc:
            self._record(task, prompt_version, "error", latency=started, note=str(exc)[:500])
            raise
        self._record(task, prompt_version, "ok", latency=started, model=result.model,
                     input_tokens=result.input_tokens or 0, output_tokens=result.output_tokens or 0,
                     attempts=result.attempts)
        return result

    def record_reuse(self, task: str, prompt_version: str, saved_tokens: int) -> None:
        """Log a call that was avoided because a cached result was still valid."""
        self._record(task, prompt_version, "reused", note=f"saved about {saved_tokens} tokens")

    def record_external(self, task: str, *, input_tokens: int, output_tokens: int, calls: int, note: str) -> None:
        """Log tokens spent outside this session (e.g. an acceptance run in a sandbox)."""
        self._record(task, None, "ok", input_tokens=input_tokens, output_tokens=output_tokens, attempts=calls, note=note)

    def _record(self, task: str, prompt_version: str | None, status: str, *, latency: float | None = None,
                model: str | None = None, input_tokens: int = 0, output_tokens: int = 0, attempts: int = 0,
                note: str | None = None) -> None:
        self._s.add(LLMCall(
            ts=utcnow_iso(), task=task, provider=self._inner.name, model=model, prompt_version=prompt_version,
            status=status, input_tokens=input_tokens, output_tokens=output_tokens,
            latency_ms=int((time.perf_counter() - latency) * 1000) if latency else 0, attempts=attempts,
            est_cost_usd=estimate_cost(self._settings, input_tokens, output_tokens), note=note,
        ))
        self._s.flush()
