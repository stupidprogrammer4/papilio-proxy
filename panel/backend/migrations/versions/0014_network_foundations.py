"""Preserve existing inbounds while adding cores, host groups and settings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_network_foundations"
down_revision: str | None = "0013_subscription_ip_limits"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "tbl_cores",
        *timestamps(),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.UniqueConstraint("node_id", "code", name="uq_core_node_code"),
    )
    op.add_column(
        "tbl_configurations",
        sa.Column("core_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_configurations",
        sa.Column("listen_port", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tbl_configurations",
        sa.Column("port_network", sa.String(3), nullable=True),
    )
    op.execute("""INSERT INTO tbl_cores (node_id, code, label, kind)
        SELECT node_id, CONCAT('default_',
          CASE WHEN protocol='wireguard' THEN 'wireguard'
               WHEN protocol='hysteria2' THEN 'hysteria' ELSE 'xray' END),
          label, CASE WHEN protocol='wireguard' THEN 'wireguard'
                      WHEN protocol='hysteria2' THEN 'hysteria'
                      ELSE 'xray' END FROM tbl_configurations""")
    op.execute("""UPDATE tbl_configurations c
        JOIN tbl_cores k ON k.node_id=c.node_id
        JOIN tbl_nodes n ON n.id=c.node_id
        SET c.core_id=k.id, c.listen_port=n.public_port,
            c.port_network=CASE
              WHEN c.protocol IN ('wireguard', 'hysteria2') THEN 'udp'
              ELSE 'tcp' END""")
    op.alter_column(
        "tbl_configurations",
        "core_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.alter_column(
        "tbl_configurations",
        "listen_port",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "tbl_configurations",
        "port_network",
        existing_type=sa.String(3),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_configuration_core",
        "tbl_configurations",
        "tbl_cores",
        ["core_id"],
        ["id"],
    )
    op.create_index(
        "ix_tbl_configurations_core_id", "tbl_configurations", ["core_id"]
    )
    op.create_index(
        "ix_tbl_configurations_node_id", "tbl_configurations", ["node_id"]
    )
    op.drop_constraint(
        "uq_configuration_node", "tbl_configurations", type_="unique"
    )
    op.create_unique_constraint(
        "uq_inbound_bind",
        "tbl_configurations",
        ["node_id", "listen_port", "port_network"],
    )
    op.create_table(
        "tbl_hosts",
        *timestamps(),
        sa.Column(
            "configuration_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_configurations.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "tbl_host_groups",
        *timestamps(),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "tbl_host_memberships",
        *timestamps(),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_host_groups.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "host_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_hosts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("server_name", sa.String(253), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("group_id", "host_id", name="uq_group_host"),
    )
    op.add_column(
        "tbl_plans", sa.Column("group_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_plan_group", "tbl_plans", "tbl_host_groups", ["group_id"], ["id"]
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("group_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_subscription_group",
        "tbl_subscriptions",
        "tbl_host_groups",
        ["group_id"],
        ["id"],
    )
    op.create_table(
        "tbl_preferences_revisions",
        *timestamps(),
        sa.Column("revision", sa.Integer(), nullable=False, unique=True),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column(
            "changed_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a backup to roll back this data expansion")
