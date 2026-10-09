"""Store signed SMS observations without raw bank message bodies."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_sms_events"
down_revision: str | None = "0006_renewal_recovery"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_sms_events",
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
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("sender", sa.String(100), nullable=False),
        sa.Column("text_digest", sa.String(64), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=True),
        sa.Column("bank_reference", sa.String(128), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_tbl_sms_events_event_id"),
    )


def downgrade() -> None:
    op.drop_table("tbl_sms_events")
