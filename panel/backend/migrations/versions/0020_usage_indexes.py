"""Bound current reservation scans and subscription date reads."""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_usage_indexes"
down_revision: str | None = "0019_entitlement_lifecycle"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_usage_reservations",
        "tbl_usage_grants",
        ["subscription_id", "generation", "is_closed", "mode"],
    )
    op.create_index(
        "ix_usage_profile_open",
        "tbl_usage_grants",
        ["profile_id", "generation", "is_closed"],
    )
    op.create_index(
        "ix_usage_subscription_time",
        "tbl_usage_events",
        ["subscription_id", "sampled_at"],
    )
    op.create_index(
        "ix_usage_node_time", "tbl_usage_events", ["node_id", "sampled_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_node_time", table_name="tbl_usage_events")
    op.drop_index("ix_usage_subscription_time", table_name="tbl_usage_events")
    op.drop_index("ix_usage_profile_open", table_name="tbl_usage_grants")
    op.drop_index("ix_usage_reservations", table_name="tbl_usage_grants")
