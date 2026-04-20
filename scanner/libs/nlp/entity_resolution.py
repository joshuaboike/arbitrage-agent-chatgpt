from __future__ import annotations

from scanner.libs.nlp.text import (
    extract_ram_gb,
    extract_screen_size,
    extract_storage_gb,
    normalize_text,
)
from scanner.libs.schemas import CanonicalAssetCandidate, RawListingEvent
from scanner.libs.taxonomy.service import TaxonomyService

BRAND_PATTERNS = {
    "apple": "Apple",
    "iphone": "Apple",
    "macbook": "Apple",
    "lenovo": "Lenovo",
    "thinkpad": "Lenovo",
    "nvidia": "NVIDIA",
    "rtx": "NVIDIA",
}

MODEL_PATTERNS = {
    "iphone 15 pro": ("iPhone", "iPhone 15 Pro"),
    "macbook pro 14": ("MacBook Pro", "MacBook Pro 14"),
    "thinkpad x1 carbon gen 11": ("ThinkPad", "ThinkPad X1 Carbon Gen 11"),
    "rtx 4090": ("GeForce RTX", "RTX 4090"),
}

COLOR_PATTERNS = ["silver", "space black", "black", "blue", "natural titanium", "gray"]
CARRIER_PATTERNS = ["unlocked", "verizon", "att", "t-mobile"]
CPU_PATTERNS = ["m1 pro", "m2 pro", "i7", "i9", "ryzen 7", "ryzen 9"]


class EntityResolutionService:
    def __init__(self, taxonomy_service: TaxonomyService) -> None:
        self.taxonomy_service = taxonomy_service

    def resolve(self, event: RawListingEvent) -> CanonicalAssetCandidate:
        text = normalize_text(event.title, event.description, event.model_text, event.brand)
        explanations: list[str] = []

        brand = event.brand
        if not brand:
            for token, mapped_brand in BRAND_PATTERNS.items():
                if token in text:
                    brand = mapped_brand
                    explanations.append(f"Matched brand token '{token}'.")
                    break

        product_line: str | None = None
        model: str | None = event.model_text
        for pattern, (candidate_product_line, candidate_model) in MODEL_PATTERNS.items():
            if pattern in text:
                product_line = candidate_product_line
                model = candidate_model
                explanations.append(f"Matched model phrase '{pattern}'.")
                break

        storage_gb = extract_storage_gb(text)
        ram_gb = extract_ram_gb(text)
        screen_size = extract_screen_size(text)

        carrier = next((item.title() for item in CARRIER_PATTERNS if item in text), None)
        color = next((item.title() for item in COLOR_PATTERNS if item in text), None)
        cpu = next(
            (
                item.upper() if item.startswith("i") else item.title()
                for item in CPU_PATTERNS
                if item in text
            ),
            None,
        )

        bundle = {
            "charger": True if "charger" in text or "oem charger" in text else None,
            "box": True if "box" in text else None,
            "accessories": [
                item for item in ["case", "dock", "controller", "cable"] if item in text
            ],
        }

        best_match = self.taxonomy_service.find_best_match(
            brand=brand,
            model=model,
            storage_gb=storage_gb,
            ram_gb=ram_gb,
        )

        confidence = 0.25
        if brand:
            confidence += 0.2
        if model:
            confidence += 0.25
        if storage_gb:
            confidence += 0.1
        if ram_gb:
            confidence += 0.05
        if best_match:
            confidence += 0.15
            explanations.append(f"Resolved to seeded taxonomy asset '{best_match.asset_id}'.")

        if "for parts" in text:
            confidence -= 0.05

        return CanonicalAssetCandidate(
            asset_family_id=best_match.asset_family_id if best_match else None,
            asset_id=best_match.asset_id if best_match else None,
            taxonomy_version=self.taxonomy_service.version,
            brand=brand or (best_match.brand if best_match else None),
            product_line=product_line or (best_match.product_line if best_match else None),
            model=model or (best_match.model if best_match else None),
            variant=best_match.variant if best_match else None,
            specs={
                "storage_gb": storage_gb
                or (best_match.spec_json.get("storage_gb") if best_match else None),
                "ram_gb": ram_gb or (best_match.spec_json.get("ram_gb") if best_match else None),
                "cpu": cpu or (best_match.spec_json.get("cpu") if best_match else None),
                "gpu": best_match.spec_json.get("gpu") if best_match else None,
                "screen_size": screen_size,
                "carrier": carrier,
                "color": color,
                "region": None,
                "year": best_match.spec_json.get("year") if best_match else None,
            },
            bundle=bundle,
            confidence=max(0.0, min(confidence, 0.99)),
            explanations=explanations,
        )
