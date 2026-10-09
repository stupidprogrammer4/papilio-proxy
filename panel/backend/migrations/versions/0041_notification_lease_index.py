"""Index expired delivery leases without changing recovery decisions."""

from collections.abc import Sequence

from alembic import op

revision: str = "0041_notification_lease_index"
down_revision: str | None = "0040_sms_devices"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_notification_status_lease",
        "tbl_notifications",
        ["status", "lease_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_status_lease", "tbl_notifications")
