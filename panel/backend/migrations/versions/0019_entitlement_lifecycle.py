"""Separate operational revocation from purchase refunds."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_entitlement_lifecycle"
down_revision: str | None = "0018_global_usage"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_provision_requests",
        sa.Column(
            "completion",
            sa.String(16),
            nullable=False,
            server_default="refund",
        ),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column(
            "lifecycle_checked_at", sa.DateTime(), nullable=True, index=True
        ),
    )

    # Prior renewal behavior was expiry-only; preserve it explicitly.
    op.execute(
        "UPDATE tbl_plans SET "
        "fulfillment_json=JSON_SET(fulfillment_json, "
        "'$.renewal_trigger', 'expiry') WHERE fulfillment_json IS NOT "
        "NULL AND JSON_EXTRACT(fulfillment_json, '$.renewal_trigger') "
        "IS NULL"
    )
    op.execute(
        "UPDATE tbl_subscriptions SET "
        "fulfillment_json=JSON_SET(fulfillment_json, "
        "'$.renewal_trigger', 'expiry') WHERE fulfillment_json IS NOT "
        "NULL AND JSON_EXTRACT(fulfillment_json, '$.renewal_trigger') "
        "IS NULL"
    )
    op.execute(
        "UPDATE tbl_provision_requests SET "
        "policy_json=JSON_SET(policy_json, '$.renewal_trigger', "
        "'expiry') WHERE JSON_EXTRACT(policy_json, "
        "'$.renewal_trigger') IS NULL"
    )
    op.execute(
        "UPDATE tbl_preferences_revisions SET "
        "values_json=JSON_SET(values_json, "
        "'$.fulfillment.renewal_trigger', 'expiry') WHERE "
        "JSON_TYPE(JSON_EXTRACT(values_json, "
        "'$.fulfillment'))='OBJECT' AND JSON_EXTRACT(values_json, "
        "'$.fulfillment.renewal_trigger') IS NULL"
    )


def downgrade() -> None:
    raise RuntimeError("Restore a backup to roll back entitlement lifecycle")
