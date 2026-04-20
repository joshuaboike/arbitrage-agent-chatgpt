from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    HEARTBEAT = "HEARTBEAT"


class ActionRoute(StrEnum):
    IGNORE = "IGNORE"
    STANDARD_ALERT = "STANDARD_ALERT"
    PRIORITY_ALERT = "PRIORITY_ALERT"


class FulfillmentStatus(StrEnum):
    SHIPPABLE = "SHIPPABLE"
    PICKUP_ONLY = "PICKUP_ONLY"
    UNKNOWN = "UNKNOWN"


class BaseSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class RawListingEvent(BaseSchema):
    event_id: str
    source: str
    source_listing_id: str
    event_type: EventType
    observed_at: datetime
    listing_url: str | None = None
    seller_id: str | None = None
    title: str | None = None
    description: str | None = None
    price: float | None = None
    currency: str | None = None
    shipping_price: float | None = None
    shipping_type: str | None = None
    location_text: str | None = None
    images: list[str] = Field(default_factory=list)
    category_path: list[str] = Field(default_factory=list)
    brand: str | None = None
    model_text: str | None = None
    condition_text: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    availability_status: str | None = None
    quantity: int | None = None
    seller_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class AssetSpecs(BaseSchema):
    storage_gb: int | None = None
    ram_gb: int | None = None
    cpu: str | None = None
    gpu: str | None = None
    screen_size: str | None = None
    carrier: str | None = None
    color: str | None = None
    region: str | None = None
    year: int | None = None


class AssetBundle(BaseSchema):
    charger: bool | None = None
    box: bool | None = None
    accessories: list[str] = Field(default_factory=list)


class CanonicalAssetCandidate(BaseSchema):
    asset_family_id: str | None = None
    asset_id: str | None = None
    taxonomy_version: str
    brand: str | None = None
    product_line: str | None = None
    model: str | None = None
    variant: str | None = None
    specs: AssetSpecs = Field(default_factory=AssetSpecs)
    bundle: AssetBundle = Field(default_factory=AssetBundle)
    confidence: float = 0.0
    explanations: list[str] = Field(default_factory=list)


class ConditionRisk(BaseSchema):
    grade_probs: dict[str, float] = Field(default_factory=dict)
    functional_risk: float = 0.0
    counterfeit_risk: float = 0.0
    lock_risk: float = 0.0
    missing_accessory_risk: float = 0.0
    damage_tags: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ValuationEstimate(BaseSchema):
    exit_bid_now: float
    exit_fast_sale: float
    exit_median: float
    exit_optimistic: float
    days_to_sell_distribution: dict[str, float]
    confidence: float
    comp_strategy: str
    comp_count: int
    reasons: list[str] = Field(default_factory=list)


class CostBreakdown(BaseSchema):
    acquisition_costs: float
    exit_costs: float
    carry_costs: float
    refurb_expected_cost: float
    return_reserve: float
    fraud_reserve: float
    payment_fees: float
    shipping_label_cost: float
    packaging_cost: float
    inbound_test_labor_cost: float
    reasons: list[str] = Field(default_factory=list)


class CaptureEstimate(BaseSchema):
    listing_survival_probability: float
    reply_probability: float
    ask_accept_probability: float
    close_probability: float
    local_pickup_success_probability: float
    overall_capture_probability: float
    reasons: list[str] = Field(default_factory=list)


class UnderwritingResult(BaseSchema):
    listing_pk: str
    source: str
    title: str | None = None
    ask_price: float | None = None
    canonical_asset: CanonicalAssetCandidate
    condition_risk: ConditionRisk
    valuation: ValuationEstimate
    costs: CostBreakdown
    capture: CaptureEstimate
    ev: float
    ev_lower: float
    ev_upper: float
    action_score: float
    confidence: float
    route: ActionRoute
    why_it_matters: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    model_version: str = "v1-text-only"
    scored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AlertLinks(BaseSchema):
    listing: str | None = None
    comp_sheet: str | None = None
    operator_action: str | None = None


class AlertPayload(BaseSchema):
    listing_pk: str
    source: str
    title: str | None = None
    ask_price: float | None = None
    estimated_exit_fast: float
    estimated_landed_cost: float
    ev: float
    ev_lower: float
    action_score: float
    entity_confidence: float
    condition_summary: str
    risks: list[str] = Field(default_factory=list)
    why_it_matters: list[str] = Field(default_factory=list)
    route: ActionRoute
    links: AlertLinks = Field(default_factory=AlertLinks)


class CompRecord(BaseSchema):
    comp_pk: str
    asset_id: str
    asset_family_id: str | None = None
    channel: str
    condition_bucket: str
    sale_price: float
    sale_date: datetime
    days_to_sell: float
    fees: float
    net_proceeds: float


class OutcomeRecord(BaseSchema):
    listing_pk: str
    action_taken: str
    won_flag: bool
    purchase_price: float | None = None
    landed_cost: float | None = None
    inspection_grade: str | None = None
    realized_exit_price: float | None = None
    realized_profit: float | None = None
    return_flag: bool = False
    fraud_flag: bool = False


class AssetTaxonomyRecord(BaseSchema):
    asset_id: str
    asset_family_id: str
    brand: str
    product_line: str
    model: str
    variant: str | None = None
    taxonomy_path: list[str]
    spec_json: dict[str, Any] = Field(default_factory=dict)


class RecentAlertView(BaseSchema):
    listing_pk: str
    route: ActionRoute
    ev: float
    ev_lower: float
    action_score: float
    title: str | None = None
    source: str
    scored_at: datetime


class EventEnvelope(BaseSchema):
    topic: str
    key: str | None = None
    payload: dict[str, Any]
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IngestTestListingRequest(BaseSchema):
    source: str = "test"
    source_listing_id: str
    title: str
    description: str | None = None
    price: float
    shipping_price: float = 0.0
    currency: str = "USD"
    seller_id: str | None = None
    location_text: str | None = None
    listing_url: str | None = None
    images: list[str] = Field(default_factory=list)
    category_path: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CraigslistSearchDefinition(BaseSchema):
    label: str
    site: str
    postal_code: str
    search_distance: int
    category: str
    delivery_available: bool = True
    query: str
    url: str


class TriageDecision(BaseSchema):
    accepted: bool
    stage: str = "stage0"
    normalized_title: str | None = None
    reject_reason: str | None = None
    reasons: list[str] = Field(default_factory=list)


class DetailGateDecision(BaseSchema):
    should_download_photos: bool
    fulfillment_status: FulfillmentStatus
    exclusion_reason: str | None = None
    reasons: list[str] = Field(default_factory=list)


class LotComponentCandidate(BaseSchema):
    item_type: str
    label: str
    quantity_hint: int = 1
    confidence: float
    reasons: list[str] = Field(default_factory=list)


class LotAnalysis(BaseSchema):
    is_multi_item: bool
    should_split_valuation: bool
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    component_candidates: list[LotComponentCandidate] = Field(default_factory=list)


__all__ = [
    "ActionRoute",
    "AlertPayload",
    "AlertLinks",
    "AssetTaxonomyRecord",
    "CanonicalAssetCandidate",
    "CaptureEstimate",
    "CompRecord",
    "ConditionRisk",
    "CostBreakdown",
    "CraigslistSearchDefinition",
    "DetailGateDecision",
    "EventEnvelope",
    "EventType",
    "FulfillmentStatus",
    "IngestTestListingRequest",
    "LotAnalysis",
    "LotComponentCandidate",
    "OutcomeRecord",
    "RawListingEvent",
    "RecentAlertView",
    "TriageDecision",
    "UnderwritingResult",
    "ValuationEstimate",
]
