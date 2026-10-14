"""Routes for the feature pack: documentation audit, billing insights, acceptance scorecard, AI usage."""
from __future__ import annotations

from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_session, require
from app.container import Container
from app.llm.gateway import month_prefix, pause_state, set_paused, tokens_used_this_month
from app.models import AcceptanceRun, LLMCall
from app.security import Actor, Permission
from app.services.acceptance import CRITERIA, AcceptanceHarness, view as acceptance_view
from app.services.batch_lock import exclusive
from app.services.demo_workload import load_demo_workload

router = APIRouter(prefix="/api", tags=["features"])


# ------------------------------------------------------------------ documentation audit (AI-23)
class FindingReview(BaseModel):
    decision: Literal["confirmed", "dismissed"]
    note: str | None = Field(default=None, max_length=2000)


@router.post("/patients/{patient_id}/documentation-audit")
def run_doc_audit(patient_id: str, actor: Actor = Depends(require(Permission.DOC_AUDIT_RUN)),
                  container: Container = Depends(get_container), session: Session = Depends(get_session)):
    result = container.doc_audit(session).run(patient_id, actor)
    session.commit()
    return result


@router.get("/patients/{patient_id}/documentation-audit")
def latest_doc_audit(patient_id: str, actor: Actor = Depends(require(Permission.CLINICAL_READ)),
                     container: Container = Depends(get_container), session: Session = Depends(get_session)):
    return container.doc_audit(session).latest(patient_id)


@router.post("/documentation-audit/findings/{finding_id}/review")
def review_finding(finding_id: int, body: FindingReview, actor: Actor = Depends(require(Permission.DOC_AUDIT_REVIEW)),
                   container: Container = Depends(get_container), session: Session = Depends(get_session)):
    result = container.doc_audit(session).review(finding_id, actor, body.decision, body.note)
    session.commit()
    return result


# ------------------------------------------------------------------ billing insights (AI-18)
class BaselineIn(BaseModel):
    category: str
    minutes_per_case: float = Field(gt=0, le=600)
    sample_size: int = Field(ge=1, le=100000)
    source: str = Field(min_length=3, max_length=500)


@router.get("/billing/insights")
def billing_insights(actor: Actor = Depends(require(Permission.BILLING_INSIGHTS)),
                     container: Container = Depends(get_container), session: Session = Depends(get_session)):
    svc = container.billing_insights(session)
    return svc.metrics() | {"baselines": svc.baselines()}


@router.get("/billing/insights.csv", response_class=PlainTextResponse)
def billing_insights_csv(actor: Actor = Depends(require(Permission.BILLING_INSIGHTS)),
                         container: Container = Depends(get_container), session: Session = Depends(get_session)):
    container.audit(session).record(actor=actor, action="billing.insights.export", entity_type="report", entity_id="cases_csv")
    session.commit()
    return PlainTextResponse(container.billing_insights(session).export_csv(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="billing-cases.csv"'})


@router.post("/billing/baselines")
def add_baseline(body: BaselineIn, actor: Actor = Depends(require(Permission.BASELINE_EDIT)),
                 container: Container = Depends(get_container), session: Session = Depends(get_session)):
    result = container.billing_insights(session).add_baseline(actor, category=body.category, minutes_per_case=body.minutes_per_case,
                                                              sample_size=body.sample_size, source=body.source)
    session.commit()
    return result


@router.post("/billing/baselines/demo")
def demo_baselines(actor: Actor = Depends(require(Permission.BASELINE_EDIT)),
                   container: Container = Depends(get_container), session: Session = Depends(get_session)):
    n = container.billing_insights(session).load_demo_baselines(actor)
    session.commit()
    return {"loaded": n, "synthetic": True}


@router.post("/billing/queues/{queue}/demo-workload")
def demo_workload(queue: str, actor: Actor = Depends(require(Permission.DEMO_WORKLOAD)),
                  container: Container = Depends(get_container), session: Session = Depends(get_session)):
    with exclusive(queue, "Load demo workload"):
        agent = container.billing_agent(session)
        out = load_demo_workload(agent, queue, actor)
        container.audit(session).record(actor=actor, action="billing.demo_workload.loaded", entity_type="queue", entity_id=queue,
                                        detail={"moved": len(out["moved"]), "skipped": len(out["skipped"])})
        session.commit()
    return out


# ------------------------------------------------------------------ acceptance scorecard (WBS #18)
@router.get("/acceptance/criteria")
def acceptance_criteria(actor: Actor = Depends(require(Permission.ACCEPTANCE_READ))):
    return [{"id": c[0], "proof": c[1], "area": c[2], "requirement": c[3], "threshold": c[4], "hard_gate": c[5]} for c in CRITERIA]


@router.get("/acceptance/runs")
def acceptance_runs(actor: Actor = Depends(require(Permission.ACCEPTANCE_READ)), session: Session = Depends(get_session)):
    runs = session.scalars(select(AcceptanceRun).order_by(AcceptanceRun.id.desc()).limit(10))
    return [acceptance_view(r) for r in runs]


@router.post("/acceptance/run")
def run_acceptance(actor: Actor = Depends(require(Permission.ACCEPTANCE_RUN)),
                   container: Container = Depends(get_container), session: Session = Depends(get_session)):
    result = AcceptanceHarness(container).run(session, actor)
    session.commit()
    return result


# ------------------------------------------------------------------ AI usage and controls (N3/N9/N10)
class PauseBody(BaseModel):
    paused: bool
    reason: str | None = Field(default=None, max_length=300)


@router.get("/ai/usage")
def ai_usage(days: int = Query(default=30, ge=1, le=365), actor: Actor = Depends(require(Permission.AI_USAGE_READ)),
             container: Container = Depends(get_container), session: Session = Depends(get_session)):
    calls = list(session.scalars(select(LLMCall).order_by(LLMCall.id.desc()).limit(5000)))
    by_task: dict[str, dict] = defaultdict(lambda: {"calls": 0, "errors": 0, "blocked": 0, "reused": 0, "input_tokens": 0,
                                                    "output_tokens": 0, "latency_ms": 0, "cost": 0.0, "cost_known": True})
    by_day: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "calls": 0})
    for c in calls:
        t = by_task[c.task]
        if c.status == "ok":
            t["calls"] += 1
            t["input_tokens"] += c.input_tokens
            t["output_tokens"] += c.output_tokens
            t["latency_ms"] += c.latency_ms
            if c.est_cost_usd is None:
                t["cost_known"] = False
            else:
                t["cost"] += c.est_cost_usd
            by_day[c.ts[:10]]["tokens"] += c.input_tokens + c.output_tokens
            by_day[c.ts[:10]]["calls"] += 1
        elif c.status == "error":
            t["errors"] += 1
        elif c.status == "blocked":
            t["blocked"] += 1
        elif c.status == "reused":
            t["reused"] += 1
    tasks = []
    for name, t in sorted(by_task.items()):
        avg = round(t["latency_ms"] / t["calls"]) if t["calls"] else None
        tasks.append({"task": name, **{k: v for k, v in t.items() if k not in ("latency_ms", "cost", "cost_known")},
                      "avg_latency_ms": avg, "est_cost_usd": round(t["cost"], 4) if t["cost_known"] and t["calls"] else None})
    s = container.settings
    used = tokens_used_this_month(session)
    return {
        "provider": container.llm.name,
        "model": s.gemini_model if container.llm.name == "gemini" else (s.anthropic_model if container.llm.name == "anthropic" else "mock"),
        "month": month_prefix(), "tokens_this_month": used, "monthly_budget": s.llm_monthly_token_budget,
        "budget_used": round(used / s.llm_monthly_token_budget, 3) if s.llm_monthly_token_budget else None,
        "prices_configured": s.llm_price_input_per_mtok is not None and s.llm_price_output_per_mtok is not None,
        "pause": pause_state(session), "by_task": tasks,
        "by_day": [{"day": d, **v} for d, v in sorted(by_day.items())][-days:],
        "recent": [{"ts": c.ts, "task": c.task, "status": c.status, "model": c.model, "prompt_version": c.prompt_version,
                    "tokens": c.input_tokens + c.output_tokens, "latency_ms": c.latency_ms, "note": c.note} for c in calls[:50]],
    }


@router.post("/ai/pause")
def ai_pause(body: PauseBody, actor: Actor = Depends(require(Permission.AI_CONTROL)),
             container: Container = Depends(get_container), session: Session = Depends(get_session)):
    state = set_paused(session, actor, body.paused, body.reason)
    container.audit(session).record(actor=actor, action="ai.paused" if body.paused else "ai.resumed", entity_type="ai_gateway",
                                    entity_id="kill_switch", detail={"reason": body.reason})
    session.commit()
    return state
