"""Persist stable identities for atomic managed-runtime batches."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0063_managed_operation_batches"
down_revision = (
    "0062_managed_epoch_rollovers",
    "0061_managed_epoch_seals",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_managed_operation_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            DATETIME(fsp=6),
            nullable=False,
            server_default=sa.func.current_timestamp(6),
        ),
        sa.Column(
            "updated_at",
            DATETIME(fsp=6),
            nullable=False,
            server_default=sa.func.current_timestamp(6),
        ),
        sa.Column(
            "installation_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_installations.id"),
            nullable=False,
        ),
        sa.Column(
            "epoch_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_epoches.id"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("accepted_at", DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint(
            "installation_id",
            "operation",
            "request_key",
            name="uq_managed_operation_batch_request",
        ),
    )
    op.add_column(
        "tbl_managed_windows",
        sa.Column("operation_batch_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_tbl_managed_windows_operation_batch_id",
        "tbl_managed_windows",
        ["operation_batch_id"],
    )
    op.create_foreign_key(
        "fk_tbl_managed_windows_operation_batch",
        "tbl_managed_windows",
        "tbl_managed_operation_batches",
        ["operation_batch_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tbl_managed_windows_operation_batch",
        "tbl_managed_windows",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_tbl_managed_windows_operation_batch_id",
        table_name="tbl_managed_windows",
    )
    op.drop_column("tbl_managed_windows", "operation_batch_id")
    op.drop_table("tbl_managed_operation_batches")
