from __future__ import annotations

from statistics import mean

from scanner.libs.schemas import (
    CanonicalAssetCandidate,
    CompRecord,
    ConditionRisk,
    ValuationEstimate,
)

GRADE_DISCOUNT = {"A": 1.0, "B": 0.93, "C": 0.82, "D": 0.58}


def _most_likely_grade(condition_risk: ConditionRisk) -> str:
    if not condition_risk.grade_probs:
        return "B"
    return max(condition_risk.grade_probs.items(), key=lambda item: item[1])[0]


class ValuationService:
    def estimate(
        self,
        candidate: CanonicalAssetCandidate,
        condition_risk: ConditionRisk,
        comps: list[CompRecord],
    ) -> ValuationEstimate:
        grade = _most_likely_grade(condition_risk)
        exact_comps = [
            comp for comp in comps if candidate.asset_id and comp.asset_id == candidate.asset_id
        ]
        family_comps = [
            comp
            for comp in comps
            if candidate.asset_family_id and comp.asset_family_id == candidate.asset_family_id
        ]

        selected = exact_comps or family_comps
        strategy = (
            "exact_asset" if exact_comps else "asset_family" if family_comps else "fallback_prior"
        )

        if selected:
            base_net = mean(comp.net_proceeds for comp in selected)
            base_days = mean(comp.days_to_sell for comp in selected)
        else:
            base_net = 850.0
            base_days = 14.0

        adjustment = GRADE_DISCOUNT.get(grade, 0.9)
        confidence = 0.85 if exact_comps else 0.72 if family_comps else 0.45
        confidence -= min(condition_risk.functional_risk * 0.2, 0.2)

        exit_median = round(base_net * adjustment, 2)
        exit_fast_sale = round(exit_median * 0.92, 2)
        exit_bid_now = round(exit_median * 0.83, 2)
        exit_optimistic = round(exit_median * 1.06, 2)

        return ValuationEstimate(
            exit_bid_now=exit_bid_now,
            exit_fast_sale=exit_fast_sale,
            exit_median=exit_median,
            exit_optimistic=exit_optimistic,
            days_to_sell_distribution={
                "p25": max(round(base_days * 0.7, 1), 1.0),
                "p50": round(base_days, 1),
                "p75": round(base_days * 1.4, 1),
            },
            confidence=max(confidence, 0.2),
            comp_strategy=strategy,
            comp_count=len(selected),
            reasons=[
                f"Selected {strategy} comp strategy.",
                f"Adjusted exit values using most likely condition grade {grade}.",
            ],
        )
