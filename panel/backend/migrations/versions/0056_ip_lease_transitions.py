"""Track issued leases without inventing historical expiry bounds."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0056_ip_lease_transitions"
down_revision = "0055_purchased_ip_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_ip_lease_states",
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
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("history_complete", sa.Boolean(), nullable=False),
        sa.Column("issued_until", DATETIME(fsp=6), nullable=True),
        sa.Column("pending_policy_json", sa.Text(), nullable=True),
        sa.Column("previous_policy_json", sa.Text(), nullable=True),
        sa.Column("previous_source", sa.String(32), nullable=True),
        sa.Column("transition_mode", sa.String(32), nullable=True),
        sa.Column("drain_until", DATETIME(fsp=6), nullable=True),
        sa.Column("blocked_reason", sa.String(64), nullable=True),
        sa.UniqueConstraint("subscription_id", name="uq_ip_lease_state"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM tbl_ip_lease_states")
    ):
        raise RuntimeError(
            "Downgrade would lose issued IP leases or transitions"
        )
    op.drop_table("tbl_ip_lease_states")
