"""Persist the latest authenticated SMS bridge health snapshot."""

import sqlalchemy as sa
from alembic import op

revision = "0069_sms_device_health"
down_revision = "0068_receipt_annotations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_sms_devices",
        sa.Column("status_received_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tbl_sms_devices",
        sa.Column("pending_event_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tbl_sms_devices",
        sa.Column("permission_granted", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "tbl_sms_devices",
        sa.Column("delivery_state", sa.String(32), nullable=True),
    )
    op.add_column(
        "tbl_sms_devices",
        sa.Column("last_acknowledged_event_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "tbl_sms_devices",
        sa.Column("last_error_code", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_sms_devices", "last_error_code")
    op.drop_column("tbl_sms_devices", "last_acknowledged_event_id")
    op.drop_column("tbl_sms_devices", "delivery_state")
    op.drop_column("tbl_sms_devices", "permission_granted")
    op.drop_column("tbl_sms_devices", "pending_event_count")
    op.drop_column("tbl_sms_devices", "status_received_at")
