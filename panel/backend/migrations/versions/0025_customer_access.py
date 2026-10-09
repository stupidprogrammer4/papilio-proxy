"""Separate customer account, service and automatic-renewal access."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_customer_access"
down_revision: str | None = "0024_subscription_suspension"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_customers",
        sa.Column(
            "service_hold_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tbl_customers",
        sa.Column(
            "services_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "tbl_customers",
        sa.Column(
            "renewals_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "tbl_customers",
        sa.Column(
            "service_hold_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "tbl_customers",
        sa.Column("service_hold_clock", sa.String(16), nullable=True),
    )
    op.add_column(
        "tbl_customers",
        sa.Column("service_hold_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tbl_customers",
        sa.Column("service_hold_reason", sa.String(250), nullable=True),
    )
    op.add_column(
        "tbl_customers",
        sa.Column("service_hold_by_staff_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_customer_service_hold_staff",
        "tbl_customers",
        "tbl_staff",
        ["service_hold_by_staff_id"],
        ["id"],
    )
    op.create_index(
        "ix_customer_services_enabled",
        "tbl_customers",
        ["services_enabled", "id"],
    )
    op.create_index(
        "ix_customer_hold_pending",
        "tbl_customers",
        ["service_hold_pending", "service_hold_at", "id"],
    )
    op.create_table(
        "tbl_customer_access_changes",
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
        sa.Column("request_key", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.Column("previous_json", sa.Text(), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
        sa.Column("clock", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tbl_customer_access_changes")
    op.drop_index("ix_customer_services_enabled", table_name="tbl_customers")
    op.drop_index("ix_customer_hold_pending", table_name="tbl_customers")
    op.drop_constraint(
        "fk_customer_service_hold_staff", "tbl_customers", type_="foreignkey"
    )
    op.drop_column("tbl_customers", "service_hold_by_staff_id")
    op.drop_column("tbl_customers", "service_hold_reason")
    op.drop_column("tbl_customers", "service_hold_at")
    op.drop_column("tbl_customers", "service_hold_clock")
    op.drop_column("tbl_customers", "service_hold_revision")
    op.drop_column("tbl_customers", "renewals_enabled")
    op.drop_column("tbl_customers", "services_enabled")
    op.drop_column("tbl_customers", "service_hold_pending")
