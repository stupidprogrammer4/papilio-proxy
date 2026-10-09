"""Explicit free trial entitlements and policy snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_trials"
down_revision: str | None = "0029_notifications"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_subscriptions",
        sa.Column(
            "entitlement_kind",
            sa.String(16),
            nullable=False,
            server_default="paid",
        ),
    )
    op.add_column(
        "tbl_subscriptions", sa.Column("trial_policy_json", sa.Text())
    )


def downgrade() -> None:
    op.drop_column("tbl_subscriptions", "trial_policy_json")
    op.drop_column("tbl_subscriptions", "entitlement_kind")
