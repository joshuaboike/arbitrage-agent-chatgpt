from __future__ import annotations

from scanner.libs.schemas import ActionRoute, AlertPayload, UnderwritingResult
from scanner.libs.utils.config import PolicySettings


class PolicyEngine:
    def __init__(self, settings: PolicySettings) -> None:
        self.settings = settings

    def route(self, result: UnderwritingResult) -> ActionRoute:
        if (
            result.ev_lower > self.settings.priority_alert_ev
            and result.action_score > self.settings.priority_action_score
            and result.capture.overall_capture_probability >= self.settings.min_capture_probability
            and result.canonical_asset.confidence >= 0.8
            and result.condition_risk.counterfeit_risk < 0.2
            and result.condition_risk.lock_risk < 0.2
        ):
            return ActionRoute.PRIORITY_ALERT

        if (
            result.ev > self.settings.standard_alert_ev
            and result.capture.overall_capture_probability >= self.settings.min_capture_probability
        ):
            return ActionRoute.STANDARD_ALERT

        return ActionRoute.IGNORE

    def build_alert(self, result: UnderwritingResult) -> AlertPayload:
        summary_bits = []
        grade = max(result.condition_risk.grade_probs.items(), key=lambda item: item[1])[0]
        summary_bits.append(f"Likely Grade {grade}")
        if result.canonical_asset.bundle.charger:
            summary_bits.append("charger included")
        if result.condition_risk.damage_tags:
            summary_bits.append(", ".join(result.condition_risk.damage_tags))

        landed_cost = result.ask_price or 0.0
        landed_cost += result.costs.acquisition_costs
        landed_cost += result.costs.refurb_expected_cost

        return AlertPayload(
            listing_pk=result.listing_pk,
            source=result.source,
            title=result.title,
            ask_price=result.ask_price,
            estimated_exit_fast=result.valuation.exit_fast_sale,
            estimated_landed_cost=round(landed_cost, 2),
            ev=result.ev,
            ev_lower=result.ev_lower,
            action_score=result.action_score,
            entity_confidence=result.canonical_asset.confidence,
            condition_summary=", ".join(summary_bits),
            risks=result.risks,
            why_it_matters=result.why_it_matters,
            route=result.route,
            links={
                "listing": None,
                "comp_sheet": None,
                "operator_action": f"/listings/{result.listing_pk}",
            },
        )
