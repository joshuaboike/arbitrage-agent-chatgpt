from __future__ import annotations

from scanner.libs.schemas import CostBreakdown, RawListingEvent


class CostEngine:
    def estimate(self, event: RawListingEvent) -> CostBreakdown:
        price = event.price or 0.0
        shipping_price = event.shipping_price or 0.0

        payment_fees = round(price * 0.03, 2)
        exit_costs = round(price * 0.12, 2)
        carry_costs = round(price * 0.01, 2)
        refurb_expected_cost = 35.0
        return_reserve = round(price * 0.04, 2)
        fraud_reserve = round(price * 0.015, 2)
        shipping_label_cost = 12.0 if shipping_price == 0 else shipping_price
        packaging_cost = 4.0
        inbound_test_labor_cost = 15.0

        acquisition_costs = round(payment_fees + shipping_label_cost + packaging_cost, 2)

        return CostBreakdown(
            acquisition_costs=acquisition_costs,
            exit_costs=exit_costs,
            carry_costs=carry_costs,
            refurb_expected_cost=refurb_expected_cost,
            return_reserve=return_reserve,
            fraud_reserve=fraud_reserve,
            payment_fees=payment_fees,
            shipping_label_cost=shipping_label_cost,
            packaging_cost=packaging_cost,
            inbound_test_labor_cost=inbound_test_labor_cost,
            reasons=[
                "Applied baseline marketplace and payment fee assumptions.",
                "Included packaging, shipping, and inbound inspection labor reserves.",
            ],
        )
