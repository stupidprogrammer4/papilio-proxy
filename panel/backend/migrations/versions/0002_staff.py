"""Add server-side staff scopes and revocable sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_staff"
down_revision: str | None = "0001_plans"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_staff",
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
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("username", name="uq_tbl_staff_username"),
    )
    op.create_table(
        "tbl_staff_grants",
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            primary_key=True,
        ),
        sa.Column("scope", sa.String(64), primary_key=True),
    )
    op.create_table(
        "tbl_staff_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("tbl_staff_sessions")
    op.drop_table("tbl_staff_grants")
    op.drop_table("tbl_staff")
