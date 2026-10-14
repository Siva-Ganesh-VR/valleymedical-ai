"""Wires adapters, LLM client and services together. Tests build their own container."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.billing.base import BillingQueueAdapter
from app.adapters.billing.mock import MockBillingQueueAdapter
from app.adapters.meditab.base import MeditabAdapter
from app.adapters.meditab.mock import MockMeditabAdapter
from app.agents.billing_agent import BillingAgent
from app.audit import AuditLogger
from app.config import Settings
from app.db import Base, build_engine, build_sessionmaker
from app.llm.client import LLMClient, build_llm_client
from app.llm.gateway import LLMGateway
from app.services.chronic_pain import ChronicPainService
from app.services.doc_audit import DocumentationAuditService
from app.services.billing_insights import BillingInsightsService
from app.services.clinical_record import ClinicalRecordService
from app.services.exceptions import ExceptionService
from app.services.patient_matching import PatientMatcher
from app.services.summary import PreVisitSummaryService


@dataclass
class Container:
    settings: Settings
    engine: Engine
    sessionmaker: sessionmaker
    meditab: MeditabAdapter
    billing: BillingQueueAdapter
    llm: LLMClient
    clock: Callable[[], date]

    # Per-request service factories (services share the request's session).
    def audit(self, s: Session) -> AuditLogger:
        return AuditLogger(s)

    def exceptions(self, s: Session) -> ExceptionService:
        return ExceptionService(s, self.audit(s))

    def matcher(self) -> PatientMatcher:
        return PatientMatcher(self.meditab)

    def records(self, s: Session) -> ClinicalRecordService:
        return ClinicalRecordService(self.meditab, self.matcher(), self.exceptions(s), self.audit(s))

    def ai(self, s: Session) -> LLMGateway:
        """Every model call goes through the metered gateway (budget, kill switch, usage log)."""
        return LLMGateway(self.llm, s, self.settings)

    def summaries(self, s: Session) -> PreVisitSummaryService:
        return PreVisitSummaryService(self.records(s), self.ai(s), self.audit(s), self.exceptions(s), session=s)

    def billing_insights(self, s: Session) -> BillingInsightsService:
        return BillingInsightsService(s, self.billing, self.audit(s))

    def doc_audit(self, s: Session) -> DocumentationAuditService:
        return DocumentationAuditService(s, self.records(s), self.ai(s), self.audit(s), self.clock)

    def chronic_pain(self, s: Session) -> ChronicPainService:
        return ChronicPainService(self.records(s))

    def billing_agent(self, s: Session) -> BillingAgent:
        return BillingAgent(session=s, settings=self.settings, billing=self.billing, records=self.records(s),
                            matcher=self.matcher(), llm=self.ai(s), audit=self.audit(s),
                            exceptions=self.exceptions(s), clock=self.clock)


def build_container(settings: Settings | None = None, *, llm: LLMClient | None = None,
                    meditab: MeditabAdapter | None = None, billing: BillingQueueAdapter | None = None) -> Container:
    settings = settings or Settings()
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(engine)
    fixed = settings.as_of_date
    return Container(
        settings=settings,
        engine=engine,
        sessionmaker=build_sessionmaker(engine),
        meditab=meditab or MockMeditabAdapter.from_file(settings.meditab_fixture),
        billing=billing or MockBillingQueueAdapter.from_file(settings.billing_fixture),
        llm=llm or build_llm_client(settings),
        clock=(lambda: fixed) if fixed else date.today,
    )
