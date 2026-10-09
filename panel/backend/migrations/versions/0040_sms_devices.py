"""Enroll revocable phone keys and preserve authenticated SMS provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_sms_devices"
down_revision: str | None = "0039_configuration_json_payloads"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_sms_devices",
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
            "approval_mode",
            sa.String(16),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "destination_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_payment_destinations.id"),
            nullable=True,
        ),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("senders_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.add_column(
        "tbl_sms_events",
        sa.Column("device_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sms_event_device",
        "tbl_sms_events",
        "tbl_sms_devices",
        ["device_id"],
        ["id"],
    )
    op.create_index(
        "ix_tbl_sms_events_device_id", "tbl_sms_events", ["device_id"]
    )

    op.add_column(
        "tbl_topups",
        sa.Column("approved_by_device_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_topups",
        sa.Column("approved_by_sms_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_topup_device",
        "tbl_topups",
        "tbl_sms_devices",
        ["approved_by_device_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_topup_sms",
        "tbl_topups",
        "tbl_sms_events",
        ["approved_by_sms_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_topup_sms", "tbl_topups", ["approved_by_sms_id"]
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM tbl_sms_devices LIMIT 1"))
        .first()
        is not None
    ):
        raise RuntimeError(
            "Restore a backup instead of discarding enrolled device provenance"
        )
    op.drop_constraint("fk_topup_device", "tbl_topups", type_="foreignkey")
    op.drop_constraint("fk_topup_sms", "tbl_topups", type_="foreignkey")
    op.drop_constraint("uq_topup_sms", "tbl_topups", type_="unique")
    op.drop_column("tbl_topups", "approved_by_device_id")
    op.drop_column("tbl_topups", "approved_by_sms_id")
    op.drop_constraint(
        "fk_sms_event_device", "tbl_sms_events", type_="foreignkey"
    )
    op.drop_index("ix_tbl_sms_events_device_id", "tbl_sms_events")
    op.drop_column("tbl_sms_events", "device_id")
    op.drop_table("tbl_sms_devices")
