"""Add triage results table for Craigslist gating outputs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260420_0002"
down_revision = "20260419_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "triage_results",
        sa.Column("triage_pk", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "listing_pk",
            sa.String(length=64),
            sa.ForeignKey("listings.listing_pk"),
            nullable=False,
            unique=True,
        ),
        sa.Column("stage_zero_json", sa.JSON(), nullable=False),
        sa.Column("lot_analysis_json", sa.JSON(), nullable=False),
        sa.Column("detail_gate_json", sa.JSON(), nullable=True),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("triage_results")
