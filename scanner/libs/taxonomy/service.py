from __future__ import annotations

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
        candidates: list[tuple[int, AssetTaxonomyRecord]] = []

        for asset in self._assets:
            score = 0
            if asset.brand.lower() == normalized_brand and normalized_brand:
                score += 30
            if asset.model.lower() == normalized_model and normalized_model:
                score += 40
            if storage_gb and asset.spec_json.get("storage_gb") == storage_gb:
                score += 20
            if ram_gb and asset.spec_json.get("ram_gb") == ram_gb:
                score += 10
            if score:
                candidates.append((score, asset))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
