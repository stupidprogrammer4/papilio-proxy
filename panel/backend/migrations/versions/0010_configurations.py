"""Store encrypted configuration drafts and stable subscription links."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_configurations"
down_revision: str | None = "0009_purchase_key"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "tbl_configurations",
        *timestamps(),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
        ),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("encrypted_settings", sa.Text(), nullable=False),
        sa.UniqueConstraint("node_id", name="uq_configuration_node"),
    )
    op.create_table(
        "tbl_profiles",
        *timestamps(),
        sa.Column(
            "configuration_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_configurations.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("client_address", sa.String(64), nullable=True),
        sa.Column("encrypted_credentials", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "configuration_id",
            "subscription_id",
            name="uq_profile_subscription",
        ),
        sa.UniqueConstraint(
            "configuration_id", "client_address", name="uq_profile_address"
        ),
    )
    op.create_table(
        "tbl_subscription_links",
        *timestamps(),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.UniqueConstraint("subscription_id", name="uq_link_subscription"),
        sa.UniqueConstraint("token_hash", name="uq_link_token"),
    )
    op.create_index(
        "ix_subscription_renewal_scan",
        "tbl_subscriptions",
        ["auto_renew", "status", "expires_at"],
    )
    op.create_index(
        "ix_probe_network_time_node",
        "tbl_probes",
        ["client_network", "sampled_at", "node_id"],
    )
    op.create_index(
        "ix_sms_amount_time", "tbl_sms_events", ["amount_rial", "sent_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_sms_amount_time", table_name="tbl_sms_events")
    op.drop_index("ix_probe_network_time_node", table_name="tbl_probes")
    op.drop_index(
        "ix_subscription_renewal_scan", table_name="tbl_subscriptions"
    )
    op.drop_table("tbl_subscription_links")
    op.drop_table("tbl_profiles")
    op.drop_table("tbl_configurations")
