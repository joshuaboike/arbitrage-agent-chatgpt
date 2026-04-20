"""Add photo review fields to triage_results and listing_images."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260420_0004"
down_revision = "20260420_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("triage_results", sa.Column("photo_review_json", sa.JSON(), nullable=True))
    op.add_column(
        "triage_results",
        sa.Column("photo_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("listing_images", sa.Column("local_path", sa.String(length=1000), nullable=True))
    op.add_column(
        "listing_images", sa.Column("content_type", sa.String(length=128), nullable=True)
    )
    op.add_column("listing_images", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.add_column(
        "listing_images",
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("listing_images", "downloaded_at")
    op.drop_column("listing_images", "size_bytes")
    op.drop_column("listing_images", "content_type")
    op.drop_column("listing_images", "local_path")
    op.drop_column("triage_results", "photo_reviewed_at")
    op.drop_column("triage_results", "photo_review_json")
