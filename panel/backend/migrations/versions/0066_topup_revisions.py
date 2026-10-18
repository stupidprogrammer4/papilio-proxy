"""Add optimistic revisions to top-up reviews."""

import sqlalchemy as sa
from alembic import op

revision = "0066_topup_revisions"
down_revision = "0065_receipt_ocr_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_topups",
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_topups", "revision")
