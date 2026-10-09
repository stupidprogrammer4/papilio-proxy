"""Private support threads and immutable message/state history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_support_tickets"
down_revision: str | None = "0027_staff_roles"
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


def upgrade() -> None:
    op.create_table(
        "tbl_support_tickets",
        *persistence(),
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
        ),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("subject", sa.String(100), nullable=False),
        sa.Column("creation_hash", sa.String(64), nullable=False),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
        ),
        sa.Column("topup_id", sa.BigInteger(), sa.ForeignKey("tbl_topups.id")),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.UniqueConstraint(
            "customer_id", "request_key", name="uq_support_ticket_request"
        ),
    )
    op.create_table(
        "tbl_support_messages",
        *persistence(),
        sa.Column(
            "ticket_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_support_tickets.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "customer_id", sa.BigInteger(), sa.ForeignKey("tbl_customers.id")
        ),
        sa.Column("staff_id", sa.BigInteger(), sa.ForeignKey("tbl_staff.id")),
        sa.Column("body", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "ticket_id", "request_key", name="uq_support_message_request"
        ),
    )
    op.create_table(
        "tbl_support_state_changes",
        *persistence(),
        sa.Column(
            "ticket_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_support_tickets.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
        sa.Column(
            "customer_id", sa.BigInteger(), sa.ForeignKey("tbl_customers.id")
        ),
        sa.Column("staff_id", sa.BigInteger(), sa.ForeignKey("tbl_staff.id")),
        sa.UniqueConstraint(
            "ticket_id", "revision", name="uq_support_state_revision"
        ),
    )


def downgrade() -> None:
    op.drop_table("tbl_support_state_changes")
    op.drop_table("tbl_support_messages")
    op.drop_table("tbl_support_tickets")
