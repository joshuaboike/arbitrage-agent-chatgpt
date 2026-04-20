from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker

from scanner.libs.connectors.registry import ConnectorRegistry, build_default_registry
from scanner.libs.events.bus import InMemoryEventBus
from scanner.libs.metrics.collector import MetricsCollector
from scanner.libs.nlp.entity_resolution import EntityResolutionService
from scanner.libs.nlp.lots import LotAnalyzer
from scanner.libs.nlp.risk import TextRiskService
from scanner.libs.nlp.triage import CraigslistDetailGateService, StageZeroTriageService
from scanner.libs.policy.engine import PolicyEngine
from scanner.libs.services.pipeline import UnderwritingPipeline
from scanner.libs.storage.database import build_session_factory
from scanner.libs.taxonomy.service import TaxonomyService
from scanner.libs.utils.config import (
    AppSettings,
    CraigslistSettings,
    EbaySettings,
    PolicySettings,
)
from scanner.libs.valuation.capture import CaptureModel
from scanner.libs.valuation.costs import CostEngine
from scanner.libs.valuation.pricing import ValuationService


class ApplicationContainer:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        craigslist_settings: CraigslistSettings | None = None,
        ebay_settings: EbaySettings | None = None,
        policy_settings: PolicySettings | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.settings = settings or AppSettings.from_env()
        self.craigslist_settings = craigslist_settings or CraigslistSettings.from_env()
        self.ebay_settings = ebay_settings or EbaySettings.from_env()
        self.policy_settings = policy_settings or PolicySettings.from_env()
        self.session_factory = session_factory or build_session_factory(self.settings.database_url)
        self.bus = InMemoryEventBus(topic_prefix=self.settings.event_bus_topic_prefix)
        self.metrics = MetricsCollector()
        self.taxonomy_service = TaxonomyService()
        self.stage_zero_triage = StageZeroTriageService()
        self.detail_gate = CraigslistDetailGateService()
        self.lot_analyzer = LotAnalyzer()
        self.entity_resolution = EntityResolutionService(self.taxonomy_service)
        self.risk_service = TextRiskService()
        self.valuation_service = ValuationService()
        self.cost_engine = CostEngine()
        self.capture_model = CaptureModel()
        self.policy_engine = PolicyEngine(self.policy_settings)
        self.connector_registry: ConnectorRegistry = build_default_registry(
            craigslist_settings=self.craigslist_settings,
            ebay_settings=self.ebay_settings,
        )

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def pipeline(self, session: Session) -> UnderwritingPipeline:
        return UnderwritingPipeline(
            session=session,
            bus=self.bus,
            metrics=self.metrics,
            taxonomy_service=self.taxonomy_service,
            entity_resolution=self.entity_resolution,
            risk_service=self.risk_service,
            valuation_service=self.valuation_service,
            cost_engine=self.cost_engine,
            capture_model=self.capture_model,
            policy_engine=self.policy_engine,
        )
