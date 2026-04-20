from __future__ import annotations

from datetime import UTC, datetime

from scanner.libs.schemas import CanonicalAssetCandidate, CompRecord, ConditionRisk
from scanner.libs.valuation.pricing import ValuationService


def test_valuation_prefers_exact_asset_comps() -> None:
    service = ValuationService()
    candidate = CanonicalAssetCandidate(
        asset_family_id="apple-iphone-15-pro",
        asset_id="apple-iphone-15-pro-256-unlocked",
        taxonomy_version="test",
        brand="Apple",
        product_line="iPhone",
        model="iPhone 15 Pro",
        confidence=0.95,
    )
    risk = ConditionRisk(grade_probs={"A": 0.1, "B": 0.8, "C": 0.1}, confidence=0.9)
    comps = [
        CompRecord(
            comp_pk="comp-1",
            asset_id="apple-iphone-15-pro-256-unlocked",
            asset_family_id="apple-iphone-15-pro",
            channel="ebay",
            condition_bucket="B",
            sale_price=930.0,
            sale_date=datetime.now(UTC),
            days_to_sell=5,
            fees=90,
            net_proceeds=840.0,
        ),
        CompRecord(
            comp_pk="comp-2",
            asset_id="apple-iphone-15-pro-128-unlocked",
            asset_family_id="apple-iphone-15-pro",
            channel="ebay",
            condition_bucket="B",
            sale_price=890.0,
            sale_date=datetime.now(UTC),
            days_to_sell=7,
            fees=88,
            net_proceeds=802.0,
        ),
    ]

    valuation = service.estimate(candidate, risk, comps)

    assert valuation.comp_strategy == "exact_asset"
    assert valuation.comp_count == 1
    assert valuation.exit_median > 700


def test_valuation_falls_back_to_family_comps() -> None:
    service = ValuationService()
    candidate = CanonicalAssetCandidate(
        asset_family_id="apple-iphone-15-pro",
        asset_id=None,
        taxonomy_version="test",
        brand="Apple",
        product_line="iPhone",
        model="iPhone 15 Pro",
        confidence=0.75,
    )
    risk = ConditionRisk(grade_probs={"A": 0.0, "B": 0.4, "C": 0.6}, confidence=0.8)
    comps = [
        CompRecord(
            comp_pk="comp-1",
            asset_id="apple-iphone-15-pro-128-unlocked",
            asset_family_id="apple-iphone-15-pro",
            channel="ebay",
            condition_bucket="C",
            sale_price=800.0,
            sale_date=datetime.now(UTC),
            days_to_sell=8,
            fees=85,
            net_proceeds=715.0,
        )
    ]

    valuation = service.estimate(candidate, risk, comps)

    assert valuation.comp_strategy == "asset_family"
    assert valuation.comp_count == 1
    assert valuation.exit_fast_sale < valuation.exit_median
