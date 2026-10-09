"""Named staff roles, memberships and immutable authority history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_staff_roles"
down_revision: str | None = "0026_automation_policies"
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
        "tbl_staff_roles",
        *persistence(),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.create_table(
        "tbl_staff_role_memberships",
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff_roles.id"),
            primary_key=True,
            index=True,
        ),
    )
    op.create_table(
        "tbl_staff_role_revisions",
        *persistence(),
        sa.Column(
            "role_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff_roles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(250), nullable=False),
        sa.UniqueConstraint(
            "role_id", "revision", name="uq_staff_role_revision"
        ),
    )
    op.create_table(
        "tbl_staff_role_changes",
        *persistence(),
        sa.Column(
            "target_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "actor_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.Column("previous_json", sa.Text(), nullable=False),
        sa.Column("current_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tbl_staff_role_changes")
    op.drop_table("tbl_staff_role_revisions")
    op.drop_table("tbl_staff_role_memberships")
    op.drop_table("tbl_staff_roles")
