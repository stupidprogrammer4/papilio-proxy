"""Separate reseller authentication and customer ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_reseller_accounts"
down_revision: str | None = "0030_trials"
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


def access() -> list[sa.Column]:
    return [
        sa.Column(name, sa.Boolean(), nullable=False)
        for name in (
            "login_enabled",
            "sales_enabled",
            "renewals_enabled",
        )
    ]


def foreign(
    name: str,
    target: str,
    *,
    nullable: bool = False,
    index: bool = False,
    primary_key: bool = False,
    unique: bool = False,
) -> sa.Column:
    return sa.Column(
        name,
        sa.BigInteger(),
        sa.ForeignKey(target),
        nullable=nullable,
        index=index,
        primary_key=primary_key,
        unique=unique,
    )


def upgrade() -> None:
    op.create_table(
        "tbl_resellers",
        *persistence(),
        *access(),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        foreign("wallet_customer_id", "tbl_customers.id", unique=True),
        foreign("created_by_staff_id", "tbl_staff.id"),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "access_revision", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("policy_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "tbl_reseller_accounts",
        *persistence(),
        foreign("reseller_id", "tbl_resellers.id", index=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("scopes_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "tbl_reseller_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        foreign("account_id", "tbl_reseller_accounts.id", index=True),
        sa.Column("reseller_access_revision", sa.Integer(), nullable=False),
        sa.Column("account_revision", sa.Integer(), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
    )
    op.create_table(
        "tbl_reseller_customers",
        foreign("customer_id", "tbl_customers.id", primary_key=True),
        foreign("reseller_id", "tbl_resellers.id", index=True),
    )
    op.create_table(
        "tbl_reseller_changes",
        *persistence(),
        *access(),
        foreign("reseller_id", "tbl_resellers.id", index=True),
        foreign("staff_id", "tbl_staff.id"),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
    )
    op.create_table(
        "tbl_reseller_account_changes",
        *persistence(),
        foreign("reseller_id", "tbl_resellers.id", index=True),
        foreign("account_id", "tbl_reseller_accounts.id", index=True),
        foreign("staff_id", "tbl_staff.id", nullable=True),
        foreign("actor_account_id", "tbl_reseller_accounts.id", nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tbl_reseller_account_changes")
    op.drop_table("tbl_reseller_changes")
    op.drop_table("tbl_reseller_customers")
    op.drop_table("tbl_reseller_sessions")
    op.drop_table("tbl_reseller_accounts")
    op.drop_table("tbl_resellers")
