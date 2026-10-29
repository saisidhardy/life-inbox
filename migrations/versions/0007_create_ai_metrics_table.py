"""Create AI metrics telemetry table.

Revision ID: 0007_create_ai_metrics_table
Revises: 0006_deduplicate_tasks_by_source
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_create_ai_metrics_table"
down_revision: Optional[str] = "0006_deduplicate_tasks_by_source"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "ai_metrics" not in tables:
        op.create_table(
            "ai_metrics",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("operation", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("status", sa.Text(), nullable=False, server_default="success"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sqlite_autoincrement=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "ai_metrics" in inspector.get_table_names():
        op.drop_table("ai_metrics")
