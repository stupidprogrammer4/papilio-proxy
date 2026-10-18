"""Store encrypted, revisioned operator corrections for receipt OCR."""

import sqlalchemy as sa
from alembic import op

revision = "0068_receipt_annotations"
down_revision = "0067_pref_catalog_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_payment_receipts",
        sa.Column(
            "annotation_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "tbl_payment_receipt_annotations",
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
            "receipt_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_payment_receipts.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.Column("encrypted_fields", sa.Text(), nullable=False),
        sa.Column("encrypted_reason", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "receipt_id", "revision", name="uq_receipt_annotation_revision"
        ),
    )
    op.create_index(
        "ix_tbl_payment_receipt_annotations_receipt_id",
        "tbl_payment_receipt_annotations",
        ["receipt_id"],
    )


def downgrade() -> None:
    has_annotations = (
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM tbl_payment_receipt_annotations LIMIT 1")
        )
        .first()
    )
    if has_annotations is not None:
        raise RuntimeError(
            "Restore a backup instead of discarding receipt annotations"
        )
    op.drop_index(
        "ix_tbl_payment_receipt_annotations_receipt_id",
        table_name="tbl_payment_receipt_annotations",
    )
    op.drop_table("tbl_payment_receipt_annotations")
    op.drop_column("tbl_payment_receipts", "annotation_revision")
