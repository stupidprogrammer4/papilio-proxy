"""Persist receipt OCR events until JetStream confirms publication."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0065_receipt_ocr_outbox"
down_revision = "0064_receipt_ocr_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_receipt_ocr_outboxes",
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
            "receipt_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_payment_receipts.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("claim_token", sa.String(64), nullable=True),
        sa.Column("lease_until", DATETIME(fsp=6), nullable=True),
        sa.Column("published_at", DATETIME(fsp=6), nullable=True),
        sa.UniqueConstraint(
            "receipt_id", name="uq_receipt_ocr_outbox_receipt"
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_tbl_receipt_ocr_outboxes_status_lease",
        "tbl_receipt_ocr_outboxes",
        ["status", "lease_until", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tbl_receipt_ocr_outboxes_status_lease",
        table_name="tbl_receipt_ocr_outboxes",
    )
    op.drop_table("tbl_receipt_ocr_outboxes")
