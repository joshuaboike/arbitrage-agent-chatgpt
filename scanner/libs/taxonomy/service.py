from __future__ import annotations

import re
from collections.abc import Iterable

from scanner.libs.schemas import AssetTaxonomyRecord
from scanner.libs.taxonomy.seed import SEEDED_ASSETS, TAXONOMY_VERSION


class TaxonomyService:
    def __init__(self, assets: Iterable[AssetTaxonomyRecord] | None = None) -> None:
        self._assets = list(assets or SEEDED_ASSETS)

    @property
    def version(self) -> str:
        return TAXONOMY_VERSION

    def all_assets(self) -> list[AssetTaxonomyRecord]:
        return list(self._assets)

    def find_best_match(
        self,
        *,
        brand: str | None,
        model: str | None,
        storage_gb: int | None = None,
        ram_gb: int | None = None,
    ) -> AssetTaxonomyRecord | None:
        normalized_brand = (brand or "").lower()
        normalized_model = (model or "").lower()
        model_tokens = {
            token for token in re.findall(r"[a-z0-9]+", normalized_model) if len(token) > 1
        }
        candidates: list[tuple[int, AssetTaxonomyRecord]] = []

        if not normalized_brand or not normalized_model:
            return None

        for asset in self._assets:
            if asset.brand.lower() != normalized_brand:
                continue
            score = 0
            asset_model = asset.model.lower()
            asset_tokens = {
                token for token in re.findall(r"[a-z0-9]+", asset_model) if len(token) > 1
            }

            if asset_model == normalized_model:
                score += 70
            elif model_tokens:
                overlap = len(model_tokens & asset_tokens) / len(model_tokens)
                if overlap >= 0.8:
                    score += 35
                elif overlap >= 0.6:
                    score += 20

            if storage_gb and asset.spec_json.get("storage_gb") == storage_gb:
                score += 20
            if ram_gb and asset.spec_json.get("ram_gb") == ram_gb:
                score += 10
            if score >= 60:
                candidates.append((score, asset))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
