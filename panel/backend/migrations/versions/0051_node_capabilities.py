"""Preserve authenticated immutable node capability observation receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0051_node_capabilities"
down_revision: str | None = "0050_checkout_attempt_fences"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_node_capability_observations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
        ),
        sa.Column("report_id", sa.String(32), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_report", sa.Text(), nullable=False),
        sa.Column("observed_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("received_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint(
            "node_id", "report_id", name="uq_capability_node_report"
        ),
    )
    op.create_index(
        "ix_tbl_node_capability_observations_node_id",
        "tbl_node_capability_observations",
        ["node_id"],
    )
    op.create_index(
        "ix_tbl_node_capability_observations_observed_at",
        "tbl_node_capability_observations",
        ["observed_at"],
    )
    op.create_index(
        "ix_tbl_node_capability_observations_received_at",
        "tbl_node_capability_observations",
        ["received_at"],
    )
    op.create_index(
        "ix_capability_node_observed",
        "tbl_node_capability_observations",
        ["node_id", "observed_at", "received_at", "id"],
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM tbl_node_capability_observations")
    )
    if count:
        raise RuntimeError(
            "Downgrade would lose node capability replay receipts"
        )
    op.drop_table("tbl_node_capability_observations")
