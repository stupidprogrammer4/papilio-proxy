"""Retain encrypted server JSON revisions and their operator context."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_configuration_json_history"
down_revision: str | None = "0037_plan_limits"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_configuration_json_revisions",
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
            "configuration_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_configurations.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(250), nullable=False),
        sa.Column("encrypted_settings", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "configuration_id",
            "revision",
            name="uq_configuration_json_revision",
        ),
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM tbl_configuration_json_revisions LIMIT 1")
        )
        .first()
        is not None
    ):
        raise RuntimeError(
            "Restore a backup instead of discarding "
            "configuration revision history"
        )
    op.drop_table("tbl_configuration_json_revisions")
