from __future__ import annotations

from scanner.libs.nlp.text import normalize_text
from scanner.libs.schemas import ConditionRisk, RawListingEvent

FLAG_WEIGHTS = {
    "for parts": 0.45,
    "untested": 0.3,
    "cracked": 0.35,
    "locked": 0.5,
    "bad esn": 0.5,
    "missing charger": 0.1,
    "no returns": 0.15,
    "water damage": 0.4,
}


class TextRiskService:
    def assess(self, event: RawListingEvent) -> ConditionRisk:
        text = normalize_text(event.title, event.description, event.condition_text)
        risk_flags = [flag for flag in FLAG_WEIGHTS if flag in text]
        functional_risk = min(sum(FLAG_WEIGHTS[flag] for flag in risk_flags), 0.95)
        lock_risk = 0.8 if any(flag in {"locked", "bad esn"} for flag in risk_flags) else 0.05
        missing_accessory_risk = 0.6 if "missing charger" in risk_flags else 0.1
        counterfeit_risk = 0.2 if "replica" in text or "aftermarket" in text else 0.05

        if "for parts" in risk_flags:
            grade_probs = {"A": 0.0, "B": 0.05, "C": 0.2, "D": 0.75}
        elif risk_flags:
            grade_probs = {"A": 0.05, "B": 0.25, "C": 0.5, "D": 0.2}
        else:
            grade_probs = {"A": 0.2, "B": 0.55, "C": 0.2, "D": 0.05}

        damage_tags = [
            flag
            for flag in risk_flags
            if flag in {"cracked", "water damage", "for parts", "untested"}
        ]

        confidence = 0.8 if event.title else 0.5
        if event.description:
            confidence += 0.1

        return ConditionRisk(
            grade_probs=grade_probs,
            functional_risk=functional_risk,
            counterfeit_risk=counterfeit_risk,
            lock_risk=lock_risk,
            missing_accessory_risk=missing_accessory_risk,
            damage_tags=damage_tags,
            risk_flags=risk_flags,
            confidence=min(confidence, 0.95),
        )
