"""Store receipt OCR extraction as encrypted data."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "0064_receipt_ocr_results"
down_revision = "0063_managed_operation_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_payment_receipts",
        sa.Column("encrypted_extraction", LONGTEXT(), nullable=True),
    )
    op.add_column(
        "tbl_payment_receipts",
        sa.Column(
            "ocr_status",
            sa.String(16),
            nullable=False,
            server_default="not_requested",
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_payment_receipts", "ocr_status")
    op.drop_column("tbl_payment_receipts", "encrypted_extraction")
