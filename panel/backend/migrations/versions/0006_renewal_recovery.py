"""Allow retry after low balance and record failed provisioning refunds."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_renewal_recovery"
down_revision: str | None = "0005_subscriptions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_subscriptions",
        sa.Column("renewal_checked_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("failure_reason", sa.String(250), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column(
            "failed_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_subscriptions", "failed_by_staff_id")
    op.drop_column("tbl_subscriptions", "failure_reason")
    op.drop_column("tbl_subscriptions", "renewal_checked_at")
