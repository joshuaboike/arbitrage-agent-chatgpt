"""Initial schema for scanner v1."""

from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20260419_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listings",
        sa.Column("listing_pk", sa.String(length=64), primary_key=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_listing_id", sa.String(length=255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("shipping_price", sa.Float(), nullable=True),
        sa.Column("seller_id", sa.String(length=255), nullable=True),
        sa.Column("geo_hash", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("listing_url", sa.String(length=1000), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source", "source_listing_id", name="uq_listing_source_id"),
    )

    op.create_table(
        "listing_images",
        sa.Column("image_pk", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("listing_pk", sa.String(length=64), sa.ForeignKey("listings.listing_pk"), nullable=False),
        sa.Column("image_url", sa.String(length=1000), nullable=False),
        sa.Column("image_hash", sa.String(length=128), nullable=True),
        sa.Column("perceptual_hash", sa.String(length=128), nullable=True),
        sa.Column("embedding_vector", sa.JSON(), nullable=True),
    )

    op.create_table(
        "assets",
        sa.Column("asset_id", sa.String(length=100), primary_key=True),
        sa.Column("asset_family_id", sa.String(length=100), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("variant", sa.String(length=200), nullable=True),
        sa.Column("taxonomy_path", sa.JSON(), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False),
    )

    op.create_table(
        "listing_asset_links",
        sa.Column("link_pk", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("listing_pk", sa.String(length=64), sa.ForeignKey("listings.listing_pk"), nullable=False),
        sa.Column("asset_id", sa.String(length=100), sa.ForeignKey("assets.asset_id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("link_method", sa.String(length=64), nullable=False),
        sa.Column("explanation_json", sa.JSON(), nullable=False),
    )

    op.create_table(
        "underwriting_scores",
        sa.Column("underwriting_pk", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("listing_pk", sa.String(length=64), sa.ForeignKey("listings.listing_pk"), nullable=False, unique=True),
        sa.Column("condition_json", sa.JSON(), nullable=False),
        sa.Column("fraud_json", sa.JSON(), nullable=False),
        sa.Column("valuation_json", sa.JSON(), nullable=False),
        sa.Column("cost_json", sa.JSON(), nullable=False),
        sa.Column("capture_json", sa.JSON(), nullable=False),
        sa.Column("ev", sa.Float(), nullable=False),
        sa.Column("ev_lower", sa.Float(), nullable=False),
        sa.Column("ev_upper", sa.Float(), nullable=False),
        sa.Column("action_score", sa.Float(), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "comps",
        sa.Column("comp_pk", sa.String(length=64), primary_key=True),
        sa.Column("asset_id", sa.String(length=100), nullable=False),
        sa.Column("asset_family_id", sa.String(length=100), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("condition_bucket", sa.String(length=8), nullable=False),
        sa.Column("sale_price", sa.Float(), nullable=False),
        sa.Column("sale_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days_to_sell", sa.Float(), nullable=False),
        sa.Column("fees", sa.Float(), nullable=False),
        sa.Column("net_proceeds", sa.Float(), nullable=False),
    )

    op.create_table(
        "outcomes",
        sa.Column("outcome_pk", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("listing_pk", sa.String(length=64), sa.ForeignKey("listings.listing_pk"), nullable=False),
        sa.Column("action_taken", sa.String(length=50), nullable=False),
        sa.Column("won_flag", sa.Boolean(), nullable=False),
        sa.Column("purchase_price", sa.Float(), nullable=True),
        sa.Column("landed_cost", sa.Float(), nullable=True),
        sa.Column("inspection_grade", sa.String(length=16), nullable=True),
        sa.Column("realized_exit_price", sa.Float(), nullable=True),
        sa.Column("realized_profit", sa.Float(), nullable=True),
        sa.Column("return_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fraud_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "sellers",
        sa.Column("source", sa.String(length=50), primary_key=True),
        sa.Column("seller_id", sa.String(length=255), primary_key=True),
        sa.Column("seller_features_json", sa.JSON(), nullable=False),
        sa.Column("historical_close_rate", sa.Float(), nullable=True),
        sa.Column("historical_issue_rate", sa.Float(), nullable=True),
    )

    seeded_assets = [
        {
            "asset_id": "apple-iphone-15-pro-256-unlocked",
            "asset_family_id": "apple-iphone-15-pro",
            "brand": "Apple",
            "model": "iPhone 15 Pro",
            "variant": "256GB Unlocked",
            "taxonomy_path": ["phones", "apple", "iphone", "iphone-15-pro"],
            "spec_json": {"storage_gb": 256, "carrier": "Unlocked"},
        },
        {
            "asset_id": "apple-macbook-pro-14-m1-pro-16-1tb",
            "asset_family_id": "apple-macbook-pro-14-m1-pro",
            "brand": "Apple",
            "model": "MacBook Pro 14",
            "variant": "M1 Pro 16GB 1TB",
            "taxonomy_path": ["laptops", "apple", "macbook-pro", "14-inch"],
            "spec_json": {"ram_gb": 16, "storage_gb": 1024, "cpu": "M1 Pro", "year": 2021},
        },
        {
            "asset_id": "nvidia-rtx-4090-founders",
            "asset_family_id": "nvidia-rtx-4090",
            "brand": "NVIDIA",
            "model": "RTX 4090",
            "variant": "Founders Edition",
            "taxonomy_path": ["gpus", "nvidia", "rtx-4090"],
            "spec_json": {"gpu": "RTX 4090"},
        },
    ]

    asset_table = sa.table(
        "assets",
        sa.column("asset_id", sa.String),
        sa.column("asset_family_id", sa.String),
        sa.column("brand", sa.String),
        sa.column("model", sa.String),
        sa.column("variant", sa.String),
        sa.column("taxonomy_path", sa.JSON),
        sa.column("spec_json", sa.JSON),
    )
    op.bulk_insert(asset_table, seeded_assets)

    comp_table = sa.table(
        "comps",
        sa.column("comp_pk", sa.String),
        sa.column("asset_id", sa.String),
        sa.column("asset_family_id", sa.String),
        sa.column("channel", sa.String),
        sa.column("condition_bucket", sa.String),
        sa.column("sale_price", sa.Float),
        sa.column("sale_date", sa.DateTime(timezone=True)),
        sa.column("days_to_sell", sa.Float),
        sa.column("fees", sa.Float),
        sa.column("net_proceeds", sa.Float),
    )
    op.bulk_insert(
        comp_table,
        [
            {
                "comp_pk": "comp-iphone-15-pro-1",
                "asset_id": "apple-iphone-15-pro-256-unlocked",
                "asset_family_id": "apple-iphone-15-pro",
                "channel": "ebay",
                "condition_bucket": "B",
                "sale_price": 930.0,
                "sale_date": datetime(2026, 4, 1),
                "days_to_sell": 6.0,
                "fees": 118.0,
                "net_proceeds": 812.0,
            },
            {
                "comp_pk": "comp-mbp-14-1",
                "asset_id": "apple-macbook-pro-14-m1-pro-16-1tb",
                "asset_family_id": "apple-macbook-pro-14-m1-pro",
                "channel": "ebay",
                "condition_bucket": "B",
                "sale_price": 1260.0,
                "sale_date": datetime(2026, 4, 2),
                "days_to_sell": 9.0,
                "fees": 140.0,
                "net_proceeds": 1120.0,
            },
            {
                "comp_pk": "comp-rtx-4090-1",
                "asset_id": "nvidia-rtx-4090-founders",
                "asset_family_id": "nvidia-rtx-4090",
                "channel": "ebay",
                "condition_bucket": "B",
                "sale_price": 1650.0,
                "sale_date": datetime(2026, 4, 3),
                "days_to_sell": 8.0,
                "fees": 185.0,
                "net_proceeds": 1465.0,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("sellers")
    op.drop_table("outcomes")
    op.drop_table("comps")
    op.drop_table("underwriting_scores")
    op.drop_table("listing_asset_links")
    op.drop_table("assets")
    op.drop_table("listing_images")
    op.drop_table("listings")

