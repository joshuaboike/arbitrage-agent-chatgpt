from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from scanner.libs.events.bus import EventBus, Topics
from scanner.libs.metrics.collector import MetricsCollector
from scanner.libs.nlp.entity_resolution import EntityResolutionService
from scanner.libs.nlp.risk import TextRiskService
from scanner.libs.policy.engine import PolicyEngine
from scanner.libs.schemas import (
    ActionRoute,
    IngestTestListingRequest,
    RawListingEvent,
    UnderwritingResult,
)
from scanner.libs.storage.repositories import (
    AssetRepository,
    CompRepository,
    ListingRepository,
    UnderwritingRepository,
)
from scanner.libs.taxonomy.seed import SEEDED_COMPS
from scanner.libs.taxonomy.service import TaxonomyService
from scanner.libs.valuation.capture import CaptureModel
from scanner.libs.valuation.costs import CostEngine
from scanner.libs.valuation.pricing import ValuationService


class UnderwritingPipeline:
    def __init__(
        self,
        *,
        session: Session,
        bus: EventBus,
        metrics: MetricsCollector,
        taxonomy_service: TaxonomyService,
        entity_resolution: EntityResolutionService,
        risk_service: TextRiskService,
        valuation_service: ValuationService,
        cost_engine: CostEngine,
        capture_model: CaptureModel,
        policy_engine: PolicyEngine,
    ) -> None:
        self.session = session
        self.bus = bus
        self.metrics = metrics
        self.taxonomy_service = taxonomy_service
        self.entity_resolution = entity_resolution
        self.risk_service = risk_service
        self.valuation_service = valuation_service
        self.cost_engine = cost_engine
        self.capture_model = capture_model
        self.policy_engine = policy_engine
        self.listings = ListingRepository(session)
        self.assets = AssetRepository(session)
        self.comps = CompRepository(session)
        self.underwriting = UnderwritingRepository(session)

    def build_raw_event(self, request: IngestTestListingRequest) -> RawListingEvent:
        return RawListingEvent(
            event_id=str(uuid4()),
            source=request.source,
            source_listing_id=request.source_listing_id,
            event_type="CREATE",
            observed_at=datetime.now(UTC),
            listing_url=request.listing_url,
            seller_id=request.seller_id,
            title=request.title,
            description=request.description,
            price=request.price,
            currency=request.currency,
            shipping_price=request.shipping_price,
            shipping_type="shipping" if request.shipping_price else "pickup",
            location_text=request.location_text,
            images=request.images,
            category_path=request.category_path,
            attributes=request.attributes,
            raw_payload=request.model_dump(mode="json"),
        )

    def ingest(self, event: RawListingEvent):
        self.assets.seed_assets_if_missing(self.taxonomy_service.all_assets())
        self.comps.seed_if_missing(SEEDED_COMPS)
        listing = self.listings.upsert_event(event)
        self.metrics.increment("listings_ingested_total")
        self.bus.publish(
            Topics.NORMALIZED_LISTING_EVENTS,
            {"listing_pk": listing.listing_pk},
            key=listing.listing_pk,
        )
        return listing

    def underwrite(self, listing_pk: str) -> UnderwritingResult:
        event = self.listings.get_event(listing_pk)
        if event is None:
            raise ValueError(f"Listing '{listing_pk}' does not exist.")

        canonical_asset = self.entity_resolution.resolve(event)
        condition_risk = self.risk_service.assess(event)
        comps = self.comps.list_for_candidate(
            canonical_asset.asset_id, canonical_asset.asset_family_id
        )
        valuation = self.valuation_service.estimate(canonical_asset, condition_risk, comps)
        costs = self.cost_engine.estimate(event)

        spread_ratio = max(
            (valuation.exit_fast_sale - (event.price or 0.0)) / max(valuation.exit_fast_sale, 1.0),
            0.0,
        )
        capture = self.capture_model.estimate(event, spread_ratio=spread_ratio)

        acquisition_price = event.price or 0.0
        acquisition_total = acquisition_price + costs.acquisition_costs + costs.refurb_expected_cost
        monetizable_exit = valuation.exit_fast_sale - costs.exit_costs - costs.carry_costs
        probability_real = max(canonical_asset.confidence, 0.4)
        probability_as_described = max(
            0.25,
            1.0
            - (
                condition_risk.functional_risk * 0.5
                + condition_risk.counterfeit_risk * 0.25
                + condition_risk.lock_risk * 0.25
            ),
        )
        probability_close = max(0.6, 1.0 - condition_risk.functional_risk * 0.25)
        probability_available = 0.98 if event.event_type != "DELETE" else 0.0

        ev = round(
            probability_real
            * probability_as_described
            * probability_close
            * probability_available
            * monetizable_exit
            - acquisition_total,
            2,
        )
        uncertainty_penalty = (
            1.0 - valuation.confidence
        ) * 60 + condition_risk.functional_risk * 90
        ev_lower = round(ev - uncertainty_penalty, 2)
        ev_upper = round(ev + (valuation.confidence * 40), 2)
        action_score = round(ev * capture.overall_capture_probability, 2)

        why_it_matters = [
            f"Fast-sale estimate is ${valuation.exit_fast_sale:.2f}.",
            f"Comp strategy: {valuation.comp_strategy} with {valuation.comp_count} comps.",
        ]
        if acquisition_price:
            delta_percent = (
                (valuation.exit_fast_sale - acquisition_price) / acquisition_price
            ) * 100
            why_it_matters.append(f"Fast-sale anchor is {delta_percent:.1f}% above ask.")
        if canonical_asset.asset_id:
            why_it_matters.append(f"Resolved to {canonical_asset.asset_id}.")

        risks = list(condition_risk.risk_flags)
        confidence = round(
            (canonical_asset.confidence + valuation.confidence + condition_risk.confidence) / 3.0,
            3,
        )

        provisional = UnderwritingResult(
            listing_pk=listing_pk,
            source=event.source,
            title=event.title,
            ask_price=event.price,
            canonical_asset=canonical_asset,
            condition_risk=condition_risk,
            valuation=valuation,
            costs=costs,
            capture=capture,
            ev=ev,
            ev_lower=ev_lower,
            ev_upper=ev_upper,
            action_score=action_score,
            confidence=confidence,
            route=ActionRoute.IGNORE,
            why_it_matters=why_it_matters,
            risks=risks,
        )
        route = self.policy_engine.route(provisional)
        result = provisional.model_copy(update={"route": route})

        self.underwriting.save(result)
        if canonical_asset.asset_id:
            self.assets.save_asset_link(
                listing_pk=listing_pk,
                asset_id=canonical_asset.asset_id,
                confidence=canonical_asset.confidence,
                explanations=canonical_asset.explanations,
            )

        self.metrics.increment("underwriting_total")
        self.metrics.observe("ev_distribution", result.ev)
        self.bus.publish(
            Topics.UNDERWRITING_RESULTS,
            {"listing_pk": listing_pk, "route": route.value},
            key=listing_pk,
        )
        if route != ActionRoute.IGNORE:
            alert_payload = self.policy_engine.build_alert(result)
            self.bus.publish(Topics.ALERTS, alert_payload.model_dump(mode="json"), key=listing_pk)

        return result
