"""Record proxy endpoint inventory and client-network probes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_nodes"
down_revision: str | None = "0007_sms_events"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_nodes",
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
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("public_host", sa.String(255), nullable=False),
        sa.Column("public_port", sa.Integer(), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("agent_key_hash", sa.String(64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("code", name="uq_tbl_nodes_code"),
    )
    op.create_table(
        "tbl_probes",
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
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("client_network", sa.String(64), nullable=False, index=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint("event_id", name="uq_tbl_probes_event_id"),
    )


def downgrade() -> None:
    op.drop_table("tbl_probes")
    op.drop_table("tbl_nodes")
