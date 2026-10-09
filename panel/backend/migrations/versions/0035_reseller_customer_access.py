"""Preserve staff and reseller identities in customer access history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_reseller_customer_access"
down_revision: str | None = "0034_attention_payers"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "tbl_subscription_controls",
        "staff_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.add_column(
        "tbl_subscription_controls",
        sa.Column("actor_account_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column(
            "suspended_by_reseller_account_id", sa.BigInteger(), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_subscription_control_reseller_account",
        "tbl_subscription_controls",
        "tbl_reseller_accounts",
        ["actor_account_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_subscription_suspension_reseller_account",
        "tbl_subscriptions",
        "tbl_reseller_accounts",
        ["suspended_by_reseller_account_id"],
        ["id"],
    )
    op.alter_column(
        "tbl_customer_access_changes",
        "staff_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.add_column(
        "tbl_customer_access_changes",
        sa.Column("reseller_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_customer_access_changes",
        sa.Column("actor_account_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_customers",
        sa.Column(
            "service_hold_by_reseller_account_id",
            sa.BigInteger(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_customer_access_reseller",
        "tbl_customer_access_changes",
        "tbl_resellers",
        ["reseller_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_customer_access_account",
        "tbl_customer_access_changes",
        "tbl_reseller_accounts",
        ["actor_account_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_customer_hold_reseller_account",
        "tbl_customers",
        "tbl_reseller_accounts",
        ["service_hold_by_reseller_account_id"],
        ["id"],
    )


def downgrade() -> None:
    dealer_history = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM tbl_customer_access_changes "
                "WHERE staff_id IS NULL"
            )
        )
        .scalar_one()
    )
    dealer_holds = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM tbl_customers "
                "WHERE service_hold_by_reseller_account_id IS NOT NULL"
            )
        )
        .scalar_one()
    )
    dealer_controls = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM tbl_subscription_controls "
                "WHERE staff_id IS NULL"
            )
        )
        .scalar_one()
    )
    dealer_suspensions = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM tbl_subscriptions "
                "WHERE suspended_by_reseller_account_id IS NOT NULL"
            )
        )
        .scalar_one()
    )
    if dealer_history or dealer_holds or dealer_controls or dealer_suspensions:
        raise RuntimeError(
            "Reseller access history requires schema0035; restore the "
            "compatible application or an earlier verified backup."
        )
    op.drop_constraint(
        "fk_subscription_control_reseller_account",
        "tbl_subscription_controls",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_subscription_suspension_reseller_account",
        "tbl_subscriptions",
        type_="foreignkey",
    )
    op.drop_column("tbl_subscription_controls", "actor_account_id")
    op.drop_column("tbl_subscriptions", "suspended_by_reseller_account_id")
    op.alter_column(
        "tbl_subscription_controls",
        "staff_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_constraint(
        "fk_customer_hold_reseller_account",
        "tbl_customers",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_customer_access_account",
        "tbl_customer_access_changes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_customer_access_reseller",
        "tbl_customer_access_changes",
        type_="foreignkey",
    )
    op.drop_column("tbl_customers", "service_hold_by_reseller_account_id")
    op.drop_column("tbl_customer_access_changes", "actor_account_id")
    op.drop_column("tbl_customer_access_changes", "reseller_id")
    op.alter_column(
        "tbl_customer_access_changes",
        "staff_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
