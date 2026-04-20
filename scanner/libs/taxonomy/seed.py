from __future__ import annotations

from datetime import UTC, datetime

from scanner.libs.schemas import AssetTaxonomyRecord, CompRecord

TAXONOMY_VERSION = "2026.04.v1"

SEEDED_ASSETS: list[AssetTaxonomyRecord] = [
    AssetTaxonomyRecord(
        asset_id="apple-iphone-15-pro-256-unlocked",
        asset_family_id="apple-iphone-15-pro",
        brand="Apple",
        product_line="iPhone",
        model="iPhone 15 Pro",
        variant="256GB Unlocked",
        taxonomy_path=["phones", "apple", "iphone", "iphone-15-pro"],
        spec_json={"storage_gb": 256, "carrier": "Unlocked"},
    ),
    AssetTaxonomyRecord(
        asset_id="apple-iphone-15-pro-128-unlocked",
        asset_family_id="apple-iphone-15-pro",
        brand="Apple",
        product_line="iPhone",
        model="iPhone 15 Pro",
        variant="128GB Unlocked",
        taxonomy_path=["phones", "apple", "iphone", "iphone-15-pro"],
        spec_json={"storage_gb": 128, "carrier": "Unlocked"},
    ),
    AssetTaxonomyRecord(
        asset_id="apple-macbook-pro-14-m1-pro-16-1tb",
        asset_family_id="apple-macbook-pro-14-m1-pro",
        brand="Apple",
        product_line="MacBook Pro",
        model="MacBook Pro 14",
        variant="M1 Pro 16GB 1TB",
        taxonomy_path=["laptops", "apple", "macbook-pro", "14-inch"],
        spec_json={"ram_gb": 16, "storage_gb": 1024, "cpu": "M1 Pro", "year": 2021},
    ),
    AssetTaxonomyRecord(
        asset_id="lenovo-thinkpad-x1-carbon-gen11-16-512",
        asset_family_id="lenovo-thinkpad-x1-carbon-gen11",
        brand="Lenovo",
        product_line="ThinkPad",
        model="ThinkPad X1 Carbon Gen 11",
        variant="16GB 512GB",
        taxonomy_path=["laptops", "lenovo", "thinkpad", "x1-carbon"],
        spec_json={"ram_gb": 16, "storage_gb": 512, "year": 2023},
    ),
    AssetTaxonomyRecord(
        asset_id="nvidia-rtx-4090-founders",
        asset_family_id="nvidia-rtx-4090",
        brand="NVIDIA",
        product_line="GeForce RTX",
        model="RTX 4090",
        variant="Founders Edition",
        taxonomy_path=["gpus", "nvidia", "rtx-4090"],
        spec_json={"gpu": "RTX 4090"},
    ),
]

SEEDED_COMPS: list[CompRecord] = [
    CompRecord(
        comp_pk="comp-iphone-15-pro-1",
        asset_id="apple-iphone-15-pro-256-unlocked",
        asset_family_id="apple-iphone-15-pro",
        channel="ebay",
        condition_bucket="B",
        sale_price=930.0,
        sale_date=datetime(2026, 4, 1, tzinfo=UTC),
        days_to_sell=6.0,
        fees=118.0,
        net_proceeds=812.0,
    ),
    CompRecord(
        comp_pk="comp-mbp-14-1",
        asset_id="apple-macbook-pro-14-m1-pro-16-1tb",
        asset_family_id="apple-macbook-pro-14-m1-pro",
        channel="ebay",
        condition_bucket="B",
        sale_price=1325.0,
        sale_date=datetime(2026, 4, 2, tzinfo=UTC),
        days_to_sell=9.0,
        fees=145.0,
        net_proceeds=1180.0,
    ),
    CompRecord(
        comp_pk="comp-rtx-4090-1",
        asset_id="nvidia-rtx-4090-founders",
        asset_family_id="nvidia-rtx-4090",
        channel="ebay",
        condition_bucket="B",
        sale_price=1650.0,
        sale_date=datetime(2026, 4, 3, tzinfo=UTC),
        days_to_sell=8.0,
        fees=185.0,
        net_proceeds=1465.0,
    ),
]
