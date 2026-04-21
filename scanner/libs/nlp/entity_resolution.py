from __future__ import annotations

import re

from scanner.libs.nlp.text import (
    extract_ram_gb,
    extract_screen_size,
    extract_storage_gb,
    normalize_text,
)
from scanner.libs.schemas import (
    CanonicalAssetCandidate,
    LlmTriageDecision,
    PhotoReviewResult,
    RawListingEvent,
)
from scanner.libs.taxonomy.service import TaxonomyService

BRAND_PATTERNS = {
    "iphone": "Apple",
    "macbook": "Apple",
    "mac mini": "Apple",
    "apple": "Apple",
    "lenovo": "Lenovo",
    "thinkpad": "Lenovo",
    "dell": "Dell",
    "hp": "HP",
    "elitebook": "HP",
    "surface": "Microsoft",
    "microsoft": "Microsoft",
    "nvidia": "NVIDIA",
    "rtx": "NVIDIA",
}

CPU_PATTERNS = [
    "m4 max",
    "m4 pro",
    "m4",
    "m3 max",
    "m3 pro",
    "m3",
    "m2 max",
    "m2 pro",
    "m2",
    "m1 max",
    "m1 pro",
    "m1",
    "i9",
    "i7",
    "i5",
    "ryzen 9",
    "ryzen 7",
]

COLOR_PATTERNS = ["silver", "space black", "black", "blue", "gray", "midnight"]
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")


class EntityResolutionService:
    def __init__(self, taxonomy_service: TaxonomyService) -> None:
        self.taxonomy_service = taxonomy_service

    def resolve(
        self,
        event: RawListingEvent,
        *,
        photo_review: PhotoReviewResult | None = None,
        llm_triage: LlmTriageDecision | None = None,
    ) -> CanonicalAssetCandidate:
        extracted = photo_review.extracted_facts if photo_review else None
        text = normalize_text(
            event.title,
            event.description,
            event.model_text,
            event.brand,
            extracted.ocr_text if extracted else None,
            extracted.model_text if extracted else None,
            extracted.family if extracted else None,
            extracted.cpu if extracted else None,
            llm_triage.family if llm_triage else None,
            llm_triage.variant_hint if llm_triage else None,
        )
        explanations: list[str] = []

        brand = extracted.brand if extracted and extracted.brand else None
        if brand:
            explanations.append("Used brand extracted from listing images.")
        if not brand and llm_triage and llm_triage.brand:
            brand = llm_triage.brand
            explanations.append("Used brand inferred during Stage 1 text triage.")
        brand = brand or event.brand
        if not brand:
            for token, mapped_brand in BRAND_PATTERNS.items():
                if token in text:
                    brand = mapped_brand
                    explanations.append(f"Matched brand token '{token}'.")
                    break

        family = extracted.family if extracted and extracted.family else None
        if family:
            explanations.append("Used family extracted from listing images.")
        family = family or (llm_triage.family if llm_triage and llm_triage.family else None)
        family = family or _infer_family(text)

        model = extracted.model_text if extracted and extracted.model_text else None
        if model:
            explanations.append("Used model extracted from listing images.")
        model = model or event.model_text
        model = model or _infer_model(text=text, family=family)

        storage_gb = (
            extracted.storage_gb if extracted and extracted.storage_gb is not None else None
        )
        storage_gb = storage_gb or extract_storage_gb(text)
        ram_gb = extracted.ram_gb if extracted and extracted.ram_gb is not None else None
        ram_gb = ram_gb or extract_ram_gb(text)
        screen_size = extracted.screen_size if extracted and extracted.screen_size else None
        screen_size = screen_size or extract_screen_size(text)
        cpu = extracted.cpu if extracted and extracted.cpu else None
        cpu = cpu or _infer_cpu(text)
        year = extracted.year if extracted and extracted.year is not None else None
        year = year or _extract_year(text)

        bundle = {
            "charger": True
            if "charger" in text or "oem charger" in text or "power adapter" in text
            else None,
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

        confidence = 0.2
        if brand:
            confidence += 0.15
        if family:
            confidence += 0.15
        if model:
            confidence += 0.2
        if cpu:
            confidence += 0.1
        if storage_gb:
            confidence += 0.08
        if ram_gb:
            confidence += 0.08
        if extracted and extracted.model_text:
            confidence += 0.1
        if llm_triage and llm_triage.confidence:
            confidence += min(llm_triage.confidence * 0.08, 0.08)
        if best_match:
            confidence += 0.1
            explanations.append(f"Resolved to seeded taxonomy asset '{best_match.asset_id}'.")
        else:
            explanations.append(
                "No strong seeded taxonomy asset match; using evidence-derived identity."
            )

        return CanonicalAssetCandidate(
            asset_family_id=best_match.asset_family_id if best_match else None,
            asset_id=best_match.asset_id if best_match else None,
            taxonomy_version=self.taxonomy_service.version,
            brand=brand or (best_match.brand if best_match else None),
            product_line=family or (best_match.product_line if best_match else None),
            model=model or (best_match.model if best_match else None),
            variant=_build_variant(
                cpu=cpu,
                ram_gb=ram_gb,
                storage_gb=storage_gb,
                best_match_variant=best_match.variant if best_match else None,
            ),
            specs={
                "storage_gb": storage_gb
                or (best_match.spec_json.get("storage_gb") if best_match else None),
                "ram_gb": ram_gb or (best_match.spec_json.get("ram_gb") if best_match else None),
                "cpu": cpu or (best_match.spec_json.get("cpu") if best_match else None),
                "gpu": best_match.spec_json.get("gpu") if best_match else None,
                "screen_size": screen_size,
                "carrier": None,
                "color": _infer_color(text),
                "region": None,
                "year": year or (best_match.spec_json.get("year") if best_match else None),
            },
            bundle=bundle,
            confidence=max(0.0, min(confidence, 0.99)),
            explanations=explanations,
        )


def _infer_family(text: str) -> str | None:
    if "macbook pro" in text:
        return "MacBook Pro"
    if "macbook air" in text:
        return "MacBook Air"
    if "mac mini" in text:
        return "Mac mini"
    if "thinkpad x1 carbon" in text:
        return "ThinkPad X1 Carbon"
    if "thinkpad" in text:
        return "ThinkPad"
    if "latitude" in text:
        return "Latitude"
    if "xps" in text:
        return "XPS"
    if "elitebook" in text:
        return "EliteBook"
    return None


def _infer_model(*, text: str, family: str | None) -> str | None:
    if "macbook pro" in text:
        size = extract_screen_size(text)
        chip = _infer_cpu(text)
        parts = ["MacBook Pro"]
        if size:
            parts.append(f'{size}-inch')
        if chip:
            parts.append(chip)
        return " ".join(parts)
    if "macbook air" in text:
        size = extract_screen_size(text)
        chip = _infer_cpu(text)
        parts = ["MacBook Air"]
        if size:
            parts.append(f'{size}-inch')
        if chip:
            parts.append(chip)
        return " ".join(parts)
    if "mac mini" in text:
        chip = _infer_cpu(text)
        return " ".join(part for part in ["Mac mini", chip] if part)
    if "thinkpad x1 carbon" in text:
        generation_match = re.search(r"x1 carbon(?:\s+gen\s*(\d+))?", text)
        generation = generation_match.group(1) if generation_match else None
        if generation:
            return f"ThinkPad X1 Carbon Gen {generation}"
        return "ThinkPad X1 Carbon"
    return family


def _infer_cpu(text: str) -> str | None:
    for item in CPU_PATTERNS:
        if item in text:
            return item.upper() if item.startswith("i") else item.title()
    return None


def _infer_color(text: str) -> str | None:
    for item in COLOR_PATTERNS:
        if item in text:
            return item.title()
    return None


def _extract_year(text: str) -> int | None:
    match = YEAR_PATTERN.search(text)
    if match is None:
        return None
    return int(match.group(1))


def _build_variant(
    *,
    cpu: str | None,
    ram_gb: int | None,
    storage_gb: int | None,
    best_match_variant: str | None,
) -> str | None:
    parts: list[str] = []
    if cpu:
        parts.append(cpu)
    if ram_gb:
        parts.append(f"{ram_gb}GB")
    if storage_gb:
        if storage_gb >= 1024 and storage_gb % 1024 == 0:
            parts.append(f"{storage_gb // 1024}TB")
        else:
            parts.append(f"{storage_gb}GB")
    if parts:
        return " ".join(parts)
    return best_match_variant
