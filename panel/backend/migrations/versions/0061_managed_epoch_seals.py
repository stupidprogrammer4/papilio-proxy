"""Persist immutable finality receipts for managed runtime epochs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME, LONGTEXT

revision = "0061_managed_epoch_seals"
down_revision = "0060_sms_decision_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_managed_epoch_seals",
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
            "epoch_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_epoches.id"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(32), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column("acceptance_id", sa.String(32), nullable=False),
        sa.Column("accepted_at", DATETIME(fsp=6), nullable=False),
        sa.Column("encrypted_receipt", LONGTEXT(), nullable=False),
        sa.UniqueConstraint("epoch_id", name="uq_managed_epoch_seal_epoch"),
        sa.UniqueConstraint(
            "acceptance_id", name="uq_managed_epoch_seal_acceptance"
        ),
    )


def downgrade() -> None:
    op.drop_table("tbl_managed_epoch_seals")
