"""Persist owned checkout intent and immutable action replay history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_durable_checkout"
down_revision: str | None = "0048_core_usage_proof"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
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


def upgrade() -> None:
    op.create_table(
        "tbl_checkout_intents",
        *timestamps(),
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(128), nullable=False, unique=True),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("purchase_key", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "plan_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_plans.id"),
            nullable=False,
        ),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("funding_mode", sa.String(24), nullable=False),
        sa.Column("delivery_mode", sa.String(24), nullable=False),
        sa.Column("price_rial", sa.BigInteger(), nullable=False),
        sa.Column("offer_sha256", sa.String(64), nullable=False),
        sa.Column("auto_renew", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("changed_offer_action", sa.String(24), nullable=False),
        sa.Column(
            "topup_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_topups.id"),
            unique=True,
        ),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            unique=True,
        ),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("checked_at", sa.DateTime()),
    )
    op.create_index(
        "ix_tbl_checkout_intents_customer_id",
        "tbl_checkout_intents",
        ["customer_id"],
    )
    op.create_index(
        "ix_checkout_due",
        "tbl_checkout_intents",
        ["state", "checked_at", "id"],
    )
    op.create_table(
        "tbl_checkout_action_receipts",
        *timestamps(),
        sa.Column(
            "intent_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_checkout_intents.id"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(128), nullable=False, unique=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("accepted_revision", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_tbl_checkout_action_receipts_intent_id",
        "tbl_checkout_action_receipts",
        ["intent_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    intents = connection.scalar(
        sa.text("SELECT COUNT(*) FROM tbl_checkout_intents")
    )
    receipts = connection.scalar(
        sa.text("SELECT COUNT(*) FROM tbl_checkout_action_receipts")
    )
    policies = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_preferences_revisions "
            "WHERE JSON_EXTRACT(values_json, '$.purchase_checkout') "
            "IS NOT NULL "
            "AND JSON_TYPE(JSON_EXTRACT(values_json, '$.purchase_checkout')) "
            "<> 'NULL'"
        )
    )
    if intents or receipts or policies:
        raise RuntimeError(
            "Downgrade would lose durable checkout intent "
            "or action replay history or saved checkout policy"
        )
    op.drop_table("tbl_checkout_action_receipts")
    op.drop_table("tbl_checkout_intents")
