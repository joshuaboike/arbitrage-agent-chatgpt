"""Add market check fields to triage_results."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260420_0005"
down_revision = "20260420_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("triage_results", sa.Column("market_check_json", sa.JSON(), nullable=True))
    op.add_column(
        "triage_results",
        sa.Column("market_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("triage_results", "market_checked_at")
    op.drop_column("triage_results", "market_check_json")
