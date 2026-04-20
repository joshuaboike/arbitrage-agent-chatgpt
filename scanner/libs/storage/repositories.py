from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from scanner.libs.schemas import (
    ActionRoute,
    AssetTaxonomyRecord,
    CompRecord,
    DetailGateDecision,
    LlmTriageDecision,
    LotAnalysis,
    MarketCheckResult,
    OutcomeRecord,
    PhotoReviewResult,
    RawListingEvent,
    RecentAlertView,
    TriageDecision,
    UnderwritingResult,
)
from scanner.libs.storage.models import (
    AssetModel,
    CompModel,
    ListingAssetLinkModel,
    ListingImageModel,
    ListingModel,
    OutcomeModel,
    TriageResultModel,
    UnderwritingScoreModel,
)


class ListingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _find_relist_candidate(self, event: RawListingEvent) -> ListingModel | None:
        if not event.seller_id or not event.title or event.price is None:
            return None

        title = event.title.strip().lower()
        threshold_time = event.observed_at - timedelta(days=30)
        query = select(ListingModel).where(
            ListingModel.source == event.source,
            ListingModel.seller_id == event.seller_id,
            ListingModel.last_seen_at >= threshold_time,
        )
        for listing in self.session.scalars(query):
            if (listing.title or "").strip().lower() == title and listing.price is not None:
                if abs(listing.price - event.price) <= 10:
                    return listing
        return None

    def upsert_event(self, event: RawListingEvent) -> ListingModel:
        listing = self.session.scalar(
            select(ListingModel).where(
                ListingModel.source == event.source,
                ListingModel.source_listing_id == event.source_listing_id,
            )
        )
        if listing is None:
            listing = self._find_relist_candidate(event)

        if listing is None:
            listing = ListingModel(
                listing_pk=f"{event.source}-{uuid4().hex[:16]}",
                source=event.source,
                source_listing_id=event.source_listing_id,
                first_seen_at=event.observed_at,
                last_seen_at=event.observed_at,
                status=event.event_type.value,
                price=event.price,
                shipping_price=event.shipping_price,
                seller_id=event.seller_id,
                geo_hash=None,
                title=event.title,
                description=event.description,
                currency=event.currency,
                listing_url=event.listing_url,
                raw_json=event.model_dump(mode="json"),
            )
            self.session.add(listing)
        else:
            listing.last_seen_at = event.observed_at
            listing.status = event.event_type.value
            listing.price = event.price
            listing.shipping_price = event.shipping_price
            listing.title = event.title
            listing.description = event.description
            listing.currency = event.currency
            listing.listing_url = event.listing_url
            listing.raw_json = event.model_dump(mode="json")

        existing_urls = {image.image_url for image in listing.images}
        for image_url in event.images:
            if image_url not in existing_urls:
                listing.images.append(ListingImageModel(image_url=image_url))

        self.session.flush()
        return listing

    def get(self, listing_pk: str) -> ListingModel | None:
        return self.session.get(ListingModel, listing_pk)

    def get_event(self, listing_pk: str) -> RawListingEvent | None:
        listing = self.get(listing_pk)
        if listing is None:
            return None
        return RawListingEvent.model_validate(listing.raw_json)

    def update_image_metadata(
        self,
        *,
        listing_pk: str,
        image_url: str,
        local_path: str | None = None,
        content_type: str | None = None,
        size_bytes: int | None = None,
        image_hash: str | None = None,
        perceptual_hash: str | None = None,
        downloaded_at: datetime | None = None,
    ) -> ListingImageModel:
        image = self.session.scalar(
            select(ListingImageModel).where(
                ListingImageModel.listing_pk == listing_pk,
                ListingImageModel.image_url == image_url,
            )
        )
        if image is None:
            image = ListingImageModel(
                listing_pk=listing_pk,
                image_url=image_url,
            )
            self.session.add(image)

        if local_path is not None:
            image.local_path = local_path
        if content_type is not None:
            image.content_type = content_type
        if size_bytes is not None:
            image.size_bytes = size_bytes
        if image_hash is not None:
            image.image_hash = image_hash
        if perceptual_hash is not None:
            image.perceptual_hash = perceptual_hash
        if downloaded_at is not None:
            image.downloaded_at = downloaded_at

        self.session.flush()
        return image


class AssetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def seed_assets_if_missing(self, assets: list[AssetTaxonomyRecord]) -> None:
        if self.session.scalar(select(AssetModel.asset_id).limit(1)):
            return

        for asset in assets:
            self.session.add(
                AssetModel(
                    asset_id=asset.asset_id,
                    asset_family_id=asset.asset_family_id,
                    brand=asset.brand,
                    model=asset.model,
                    variant=asset.variant,
                    taxonomy_path=asset.taxonomy_path,
                    spec_json=asset.spec_json,
                )
            )

    def save_asset_link(
        self, listing_pk: str, asset_id: str, confidence: float, explanations: list[str]
    ) -> None:
        existing = self.session.scalar(
            select(ListingAssetLinkModel).where(ListingAssetLinkModel.listing_pk == listing_pk)
        )
        if existing is None:
            existing = ListingAssetLinkModel(
                listing_pk=listing_pk,
                asset_id=asset_id,
                confidence=confidence,
                link_method="rule_based",
                explanation_json=explanations,
            )
            self.session.add(existing)
        else:
            existing.asset_id = asset_id
            existing.confidence = confidence
            existing.explanation_json = explanations
        self.session.flush()


class CompRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def seed_if_missing(self, comps: list[CompRecord]) -> None:
        if self.session.scalar(select(CompModel.comp_pk).limit(1)):
            return
        for comp in comps:
            self.session.add(
                CompModel(
                    comp_pk=comp.comp_pk,
                    asset_id=comp.asset_id,
                    asset_family_id=comp.asset_family_id,
                    channel=comp.channel,
                    condition_bucket=comp.condition_bucket,
                    sale_price=comp.sale_price,
                    sale_date=comp.sale_date,
                    days_to_sell=comp.days_to_sell,
                    fees=comp.fees,
                    net_proceeds=comp.net_proceeds,
                )
            )

    def list_for_candidate(
        self, asset_id: str | None, asset_family_id: str | None
    ) -> list[CompRecord]:
        query = select(CompModel)
        if asset_id:
            query = query.where(
                (CompModel.asset_id == asset_id) | (CompModel.asset_family_id == asset_family_id)
            )
        elif asset_family_id:
            query = query.where(CompModel.asset_family_id == asset_family_id)
        else:
            query = query.limit(0)

        comps = self.session.scalars(query).all()
        return [
            CompRecord(
                comp_pk=comp.comp_pk,
                asset_id=comp.asset_id,
                asset_family_id=comp.asset_family_id,
                channel=comp.channel,
                condition_bucket=comp.condition_bucket,
                sale_price=comp.sale_price,
                sale_date=comp.sale_date,
                days_to_sell=comp.days_to_sell,
                fees=comp.fees,
                net_proceeds=comp.net_proceeds,
            )
            for comp in comps
        ]


class UnderwritingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, result: UnderwritingResult) -> UnderwritingScoreModel:
        model = self.session.scalar(
            select(UnderwritingScoreModel).where(
                UnderwritingScoreModel.listing_pk == result.listing_pk
            )
        )
        if model is None:
            model = UnderwritingScoreModel(
                listing_pk=result.listing_pk,
                condition_json=result.condition_risk.model_dump(mode="json"),
                fraud_json={
                    "counterfeit_risk": result.condition_risk.counterfeit_risk,
                    "lock_risk": result.condition_risk.lock_risk,
                },
                valuation_json=result.valuation.model_dump(mode="json"),
                cost_json=result.costs.model_dump(mode="json"),
                capture_json=result.capture.model_dump(mode="json"),
                ev=result.ev,
                ev_lower=result.ev_lower,
                ev_upper=result.ev_upper,
                action_score=result.action_score,
                route=result.route.value,
                model_version=result.model_version,
                scored_at=result.scored_at,
            )
            self.session.add(model)
        else:
            model.condition_json = result.condition_risk.model_dump(mode="json")
            model.fraud_json = {
                "counterfeit_risk": result.condition_risk.counterfeit_risk,
                "lock_risk": result.condition_risk.lock_risk,
            }
            model.valuation_json = result.valuation.model_dump(mode="json")
            model.cost_json = result.costs.model_dump(mode="json")
            model.capture_json = result.capture.model_dump(mode="json")
            model.ev = result.ev
            model.ev_lower = result.ev_lower
            model.ev_upper = result.ev_upper
            model.action_score = result.action_score
            model.route = result.route.value
            model.model_version = result.model_version
            model.scored_at = result.scored_at

        self.session.flush()
        return model

    def get(self, listing_pk: str) -> UnderwritingResult | None:
        query = (
            select(UnderwritingScoreModel, ListingModel)
            .join(ListingModel, ListingModel.listing_pk == UnderwritingScoreModel.listing_pk)
            .where(UnderwritingScoreModel.listing_pk == listing_pk)
        )
        row = self.session.execute(query).one_or_none()
        if row is None:
            return None

        score_model, listing = row
        asset_link = self.session.scalar(
            select(ListingAssetLinkModel).where(ListingAssetLinkModel.listing_pk == listing_pk)
        )
        asset_model = self.session.get(AssetModel, asset_link.asset_id) if asset_link else None
        return UnderwritingResult(
            listing_pk=listing.listing_pk,
            source=listing.source,
            title=listing.title,
            ask_price=listing.price,
            canonical_asset={
                "asset_family_id": asset_model.asset_family_id if asset_model else None,
                "asset_id": asset_model.asset_id if asset_model else None,
                "taxonomy_version": "persisted",
                "brand": asset_model.brand if asset_model else None,
                "product_line": None,
                "model": asset_model.model if asset_model else None,
                "variant": asset_model.variant if asset_model else None,
                "specs": asset_model.spec_json if asset_model else {},
                "bundle": {},
                "confidence": asset_link.confidence if asset_link else 0.0,
                "explanations": asset_link.explanation_json if asset_link else [],
            },
            condition_risk=score_model.condition_json,
            valuation=score_model.valuation_json,
            costs=score_model.cost_json,
            capture=score_model.capture_json,
            ev=score_model.ev,
            ev_lower=score_model.ev_lower,
            ev_upper=score_model.ev_upper,
            action_score=score_model.action_score,
            confidence=score_model.valuation_json.get("confidence", 0.0),
            route=ActionRoute(score_model.route),
            why_it_matters=score_model.valuation_json.get("reasons", []),
            risks=score_model.condition_json.get("risk_flags", []),
            model_version=score_model.model_version,
            scored_at=score_model.scored_at,
        )

    def recent_alerts(self, limit: int = 20) -> list[RecentAlertView]:
        query = (
            select(UnderwritingScoreModel, ListingModel)
            .join(ListingModel, ListingModel.listing_pk == UnderwritingScoreModel.listing_pk)
            .where(UnderwritingScoreModel.route != ActionRoute.IGNORE.value)
            .order_by(desc(UnderwritingScoreModel.scored_at))
            .limit(limit)
        )
        rows = self.session.execute(query).all()
        return [
            RecentAlertView(
                listing_pk=listing.listing_pk,
                route=ActionRoute(score.route),
                ev=score.ev,
                ev_lower=score.ev_lower,
                action_score=score.action_score,
                title=listing.title,
                source=listing.source,
                scored_at=score.scored_at,
            )
            for score, listing in rows
        ]


class OutcomeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, outcome: OutcomeRecord) -> OutcomeModel:
        model = OutcomeModel(**outcome.model_dump(mode="python"))
        self.session.add(model)
        self.session.flush()
        return model


class TriageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        *,
        listing_pk: str,
        stage_zero: TriageDecision,
        lot_analysis: LotAnalysis,
        detail_gate: DetailGateDecision | None = None,
        llm_triage: LlmTriageDecision | None = None,
        llm_model: str | None = None,
        photo_review: PhotoReviewResult | None = None,
        market_check: MarketCheckResult | None = None,
    ) -> TriageResultModel:
        model = self.session.scalar(
            select(TriageResultModel).where(TriageResultModel.listing_pk == listing_pk)
        )
        if model is None:
            model = TriageResultModel(
                listing_pk=listing_pk,
                stage_zero_json=stage_zero.model_dump(mode="json"),
                lot_analysis_json=lot_analysis.model_dump(mode="json"),
                detail_gate_json=detail_gate.model_dump(mode="json") if detail_gate else None,
                llm_triage_json=llm_triage.model_dump(mode="json") if llm_triage else None,
                llm_model=llm_model,
                llm_reviewed_at=datetime.now(UTC) if llm_triage else None,
                photo_review_json=photo_review.model_dump(mode="json") if photo_review else None,
                photo_reviewed_at=datetime.now(UTC) if photo_review else None,
                market_check_json=market_check.model_dump(mode="json") if market_check else None,
                market_checked_at=datetime.now(UTC) if market_check else None,
            )
            self.session.add(model)
        else:
            model.stage_zero_json = stage_zero.model_dump(mode="json")
            model.lot_analysis_json = lot_analysis.model_dump(mode="json")
            if detail_gate is not None:
                model.detail_gate_json = detail_gate.model_dump(mode="json")
            if llm_triage is not None:
                model.llm_triage_json = llm_triage.model_dump(mode="json")
                model.llm_model = llm_model
                model.llm_reviewed_at = datetime.now(UTC)
            if photo_review is not None:
                model.photo_review_json = photo_review.model_dump(mode="json")
                model.photo_reviewed_at = datetime.now(UTC)
            if market_check is not None:
                model.market_check_json = market_check.model_dump(mode="json")
                model.market_checked_at = datetime.now(UTC)

        self.session.flush()
        return model

    def count_by_source(self, source: str) -> int:
        query = (
            select(TriageResultModel.triage_pk)
            .join(ListingModel, ListingModel.listing_pk == TriageResultModel.listing_pk)
            .where(ListingModel.source == source)
        )
        return len(self.session.scalars(query).all())

    def list_stage_one_candidates(
        self,
        *,
        source: str,
        limit: int | None = None,
    ) -> list[tuple[ListingModel, TriageResultModel]]:
        query = (
            select(ListingModel, TriageResultModel)
            .join(TriageResultModel, TriageResultModel.listing_pk == ListingModel.listing_pk)
            .where(ListingModel.source == source)
            .order_by(ListingModel.first_seen_at.desc())
        )
        rows = self.session.execute(query).all()
        filtered = [
            (listing, triage)
            for listing, triage in rows
            if triage.stage_zero_json.get("accepted") is True and triage.llm_triage_json is None
        ]
        if limit is not None:
            return filtered[:limit]
        return filtered

    def count_stage_one_completed(self, source: str) -> int:
        query = (
            select(TriageResultModel)
            .join(ListingModel, ListingModel.listing_pk == TriageResultModel.listing_pk)
            .where(ListingModel.source == source)
        )
        return len(
            [
                model
                for model in self.session.scalars(query).all()
                if model.llm_triage_json is not None
            ]
        )

    def list_photo_review_candidates(
        self,
        *,
        source: str,
        limit: int | None = None,
        include_low_info_rechecks: bool = False,
    ) -> list[tuple[ListingModel, TriageResultModel]]:
        query = (
            select(ListingModel, TriageResultModel)
            .join(TriageResultModel, TriageResultModel.listing_pk == ListingModel.listing_pk)
            .where(ListingModel.source == source)
            .order_by(ListingModel.first_seen_at.desc())
        )
        rows = self.session.execute(query).all()
        filtered = []
        for listing, triage in rows:
            detail_gate = triage.detail_gate_json or {}
            if triage.stage_zero_json.get("accepted") is not True:
                continue
            if (triage.llm_triage_json or {}).get("needs_detail_fetch") is not True:
                continue
            if detail_gate.get("should_download_photos") is not True:
                continue
            if triage.photo_review_json is not None:
                if not include_low_info_rechecks:
                    continue
                photo_review = triage.photo_review_json or {}
                mismatch_flags = set(photo_review.get("mismatch_flags") or [])
                if "low_filesize_photos" not in mismatch_flags:
                    continue
            filtered.append((listing, triage))
        if limit is not None:
            return filtered[:limit]
        return filtered

    def list_market_check_candidates(
        self,
        *,
        source: str,
        limit: int | None = None,
        include_existing_rechecks: bool = False,
    ) -> list[tuple[ListingModel, TriageResultModel]]:
        query = (
            select(ListingModel, TriageResultModel)
            .join(TriageResultModel, TriageResultModel.listing_pk == ListingModel.listing_pk)
            .where(ListingModel.source == source)
            .order_by(ListingModel.first_seen_at.desc())
        )
        rows = self.session.execute(query).all()
        filtered = []
        for listing, triage in rows:
            detail_gate = triage.detail_gate_json or {}
            if triage.stage_zero_json.get("accepted") is not True:
                continue
            if (triage.llm_triage_json or {}).get("needs_detail_fetch") is not True:
                continue
            if detail_gate.get("should_download_photos") is not True:
                continue
            if triage.photo_review_json is None:
                continue
            if triage.market_check_json is not None and not include_existing_rechecks:
                continue
            filtered.append((listing, triage))
        if limit is not None:
            return filtered[:limit]
        return filtered

    def list_detail_gate_candidates(
        self,
        *,
        source: str,
        limit: int | None = None,
        include_unknown_rechecks: bool = False,
    ) -> list[tuple[ListingModel, TriageResultModel]]:
        query = (
            select(ListingModel, TriageResultModel)
            .join(TriageResultModel, TriageResultModel.listing_pk == ListingModel.listing_pk)
            .where(ListingModel.source == source)
            .order_by(ListingModel.first_seen_at.desc())
        )
        rows = self.session.execute(query).all()
        filtered = []
        for listing, triage in rows:
            if triage.stage_zero_json.get("accepted") is not True:
                continue
            llm_triage = triage.llm_triage_json or {}
            if llm_triage.get("needs_detail_fetch") is not True:
                continue
            if triage.detail_gate_json is not None:
                if not include_unknown_rechecks:
                    continue
                detail_gate = triage.detail_gate_json or {}
                should_recheck = (
                    detail_gate.get("fulfillment_status") == "UNKNOWN"
                    and detail_gate.get("should_download_photos") is False
                )
                if not should_recheck:
                    continue
            filtered.append((listing, triage))
        if limit is not None:
            return filtered[:limit]
        return filtered
