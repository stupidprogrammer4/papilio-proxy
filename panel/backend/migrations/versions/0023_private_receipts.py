"""Keep private receipt ciphertext with the transaction and backup boundary."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision: str = "0023_private_receipts"
down_revision: str | None = "0022_customer_sessions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_payment_receipts",
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
            "topup_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_topups.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("encrypted_payload", LONGTEXT(), nullable=False),
        sa.UniqueConstraint(
            "topup_id", "content_hash", name="uq_receipt_topup_content"
        ),
    )


def downgrade() -> None:
    op.drop_table("tbl_payment_receipts")
