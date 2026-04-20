from __future__ import annotations

from scanner.libs.policy.engine import PolicyEngine
from scanner.libs.schemas import (
    ActionRoute,
    CanonicalAssetCandidate,
    CaptureEstimate,
    ConditionRisk,
    CostBreakdown,
    UnderwritingResult,
    ValuationEstimate,
)
from scanner.libs.utils.config import PolicySettings


def build_result(ev: float, ev_lower: float, action_score: float) -> UnderwritingResult:
    return UnderwritingResult(
        listing_pk="listing-1",
        source="ebay",
        title="MacBook Pro 14",
        ask_price=850.0,
        canonical_asset=CanonicalAssetCandidate(
            asset_family_id="family",
            asset_id="asset",
            taxonomy_version="test",
            brand="Apple",
            product_line="MacBook Pro",
            model="MacBook Pro 14",
            confidence=0.97,
        ),
        condition_risk=ConditionRisk(
            grade_probs={"B": 0.7, "C": 0.3},
            functional_risk=0.05,
            counterfeit_risk=0.02,
            lock_risk=0.01,
            confidence=0.88,
        ),
        valuation=ValuationEstimate(
            exit_bid_now=900.0,
            exit_fast_sale=1100.0,
            exit_median=1180.0,
            exit_optimistic=1230.0,
            days_to_sell_distribution={"p25": 4, "p50": 7, "p75": 10},
            confidence=0.9,
            comp_strategy="exact_asset",
            comp_count=4,
        ),
        costs=CostBreakdown(
            acquisition_costs=60.0,
            exit_costs=120.0,
            carry_costs=10.0,
            refurb_expected_cost=25.0,
            return_reserve=15.0,
            fraud_reserve=5.0,
            payment_fees=24.0,
            shipping_label_cost=12.0,
            packaging_cost=4.0,
            inbound_test_labor_cost=15.0,
        ),
        capture=CaptureEstimate(
            listing_survival_probability=0.7,
            reply_probability=0.85,
            ask_accept_probability=0.8,
            close_probability=0.82,
            local_pickup_success_probability=0.9,
            overall_capture_probability=0.7,
        ),
        ev=ev,
        ev_lower=ev_lower,
        ev_upper=ev + 40,
        action_score=action_score,
        confidence=0.92,
        route=ActionRoute.IGNORE,
    )


def test_policy_routes_priority_alert_when_signal_is_strong() -> None:
    engine = PolicyEngine(PolicySettings.from_env())
    result = build_result(ev=140.0, ev_lower=100.0, action_score=80.0)

    assert engine.route(result) == ActionRoute.PRIORITY_ALERT


def test_policy_routes_standard_alert_when_priority_bar_is_not_met() -> None:
    engine = PolicyEngine(PolicySettings.from_env())
    result = build_result(ev=45.0, ev_lower=5.0, action_score=12.0)

    assert engine.route(result) == ActionRoute.STANDARD_ALERT
