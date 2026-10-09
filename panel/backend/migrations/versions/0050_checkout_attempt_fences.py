"""Persist owned checkout-operation fences and preserve earlier replays."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050_checkout_attempt_fences"
down_revision: str | None = "0049_durable_checkout"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_checkout_attempts",
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
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(128), nullable=False, unique=True),
        sa.Column("body_sha256", sa.String(64), nullable=True),
        sa.Column(
            "intent_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_checkout_intents.id"),
            unique=True,
        ),
        sa.Column("retired", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_tbl_checkout_attempts_customer_id",
        "tbl_checkout_attempts",
        ["customer_id"],
    )
    # Existing immutable operation bodies and links retain their exact values.
    op.execute(
        sa.text(
            "INSERT INTO tbl_checkout_attempts "
            "(created_at,updated_at,customer_id,request_key,"
            "body_sha256,intent_id,retired) "
            "SELECT created_at,updated_at,customer_id,request_key,"
            "body_sha256,id,0 "
            "FROM tbl_checkout_intents"
        )
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM tbl_checkout_attempts")
    )
    if count:
        raise RuntimeError(
            "Downgrade would lose durable checkout attempt fences"
        )
    op.drop_table("tbl_checkout_attempts")
