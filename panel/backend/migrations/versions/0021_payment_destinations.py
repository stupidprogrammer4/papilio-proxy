"""Preserve legacy top-ups and add encrypted destination snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_payment_destinations"
down_revision: str | None = "0020_usage_indexes"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_payment_destinations",
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
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("encrypted_details", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, index=True),
    )
    op.add_column(
        "tbl_topups", sa.Column("request_key", sa.String(128), nullable=True)
    )
    op.create_unique_constraint(
        "uq_topup_request_key", "tbl_topups", ["request_key"]
    )
    op.add_column(
        "tbl_topups",
        sa.Column("destination_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_topup_destination",
        "tbl_topups",
        "tbl_payment_destinations",
        ["destination_id"],
        ["id"],
    )
    op.add_column(
        "tbl_topups",
        sa.Column("encrypted_instruction", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_topups", "encrypted_instruction")
    op.drop_constraint(
        "fk_topup_destination", "tbl_topups", type_="foreignkey"
    )
    op.drop_column("tbl_topups", "destination_id")
    op.drop_constraint("uq_topup_request_key", "tbl_topups", type_="unique")
    op.drop_column("tbl_topups", "request_key")
    op.drop_table("tbl_payment_destinations")
