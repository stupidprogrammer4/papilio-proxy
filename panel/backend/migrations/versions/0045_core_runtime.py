"""Encrypted core revisions and recoverable node command leases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision: str = "0045_core_runtime"
down_revision: str | None = "0044_customer_loyalty"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def common() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "tbl_core_runtime_revisions",
        *common(),
        sa.Column(
            "core_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_cores.id"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column(
            "created_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
        ),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("entitlement_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("encrypted_payload", LONGTEXT(), nullable=False),
    )
    op.create_table(
        "tbl_core_runtime_states",
        *common(),
        sa.Column(
            "core_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_cores.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "desired_revision_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_core_runtime_revisions.id"),
        ),
        sa.Column(
            "applied_revision_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_core_runtime_revisions.id"),
        ),
        sa.Column(
            "validated_revision_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_core_runtime_revisions.id"),
        ),
        sa.Column("observed_status", sa.String(16), nullable=False),
    )
    op.create_index(
        "ix_tbl_core_runtime_revisions_core_id",
        "tbl_core_runtime_revisions",
        ["core_id"],
    )
    op.create_table(
        "tbl_core_runtime_commands",
        *common(),
        sa.Column(
            "core_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_cores.id"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reconcile_mode", sa.String(16)),
        sa.Column(
            "created_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
        ),
        sa.Column(
            "revision_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_core_runtime_revisions.id"),
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("claim_hash", sa.String(64)),
        sa.Column("claim_until", sa.DateTime()),
        sa.Column("ack_sha256", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.UniqueConstraint(
            "core_id", "request_key", name="uq_core_runtime_request"
        ),
    )
    op.create_index(
        "ix_tbl_core_runtime_commands_core_id",
        "tbl_core_runtime_commands",
        ["core_id"],
    )
    op.create_index(
        "ix_tbl_core_runtime_commands_node_id",
        "tbl_core_runtime_commands",
        ["node_id"],
    )
    op.create_index(
        "ix_tbl_core_runtime_commands_state",
        "tbl_core_runtime_commands",
        ["state"],
    )


def downgrade() -> None:
    for table in (
        "tbl_core_runtime_commands",
        "tbl_core_runtime_revisions",
        "tbl_core_runtime_states",
    ):
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1"))
            .first()
            is not None
        ):
            raise RuntimeError(
                "Restore a backup to preserve core runtime history"
            )
    op.drop_table("tbl_core_runtime_commands")
    op.drop_table("tbl_core_runtime_states")
    op.drop_table("tbl_core_runtime_revisions")
