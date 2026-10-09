"""Durable automation policies, registration state and immutable revisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_automation_policies"
down_revision: str | None = "0025_customer_access"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_automation_registrations",
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
        sa.Column("key", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("applied_revision", sa.Integer(), nullable=True),
        sa.Column("registered_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "tbl_automation_revisions",
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
        sa.Column("key", sa.String(32), nullable=False, index=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "key", "revision", name="uq_automation_key_revision"
        ),
    )


def downgrade() -> None:
    op.drop_table("tbl_automation_revisions")
    op.drop_table("tbl_automation_registrations")
