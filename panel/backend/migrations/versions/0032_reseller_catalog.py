"""Versioned reseller plan agreements and pricing history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_reseller_catalog"
down_revision: str | None = "0031_reseller_accounts"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def persistence() -> list[sa.Column]:
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


def pricing() -> list[sa.Column]:
    return [
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("price_json", sa.Text(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tbl_reseller_plans",
        *persistence(),
        *pricing(),
        sa.Column(
            "reseller_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_resellers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "plan_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_plans.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("reseller_id", "plan_id"),
    )
    op.create_table(
        "tbl_reseller_plan_changes",
        *persistence(),
        *pricing(),
        sa.Column(
            "agreement_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_reseller_plans.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(250), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tbl_reseller_plan_changes")
    op.drop_table("tbl_reseller_plans")
