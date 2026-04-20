"""Add Stage 1 LLM triage fields to triage_results."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260420_0003"
down_revision = "20260420_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("triage_results", sa.Column("llm_triage_json", sa.JSON(), nullable=True))
    op.add_column("triage_results", sa.Column("llm_model", sa.String(length=64), nullable=True))
    op.add_column(
        "triage_results",
        sa.Column("llm_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("triage_results", "llm_reviewed_at")
    op.drop_column("triage_results", "llm_model")
    op.drop_column("triage_results", "llm_triage_json")
