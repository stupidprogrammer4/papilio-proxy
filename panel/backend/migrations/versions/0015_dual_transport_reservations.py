"""Reserve each transport socket and preserve existing inbound drafts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_dual_transport_reservations"
down_revision: str | None = "0014_network_foundations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    conflicts = op.get_bind().execute(
        sa.text("""
        SELECT node_id, listen_port, network FROM (
          SELECT node_id, listen_port, 'tcp' AS network
          FROM tbl_configurations
          WHERE protocol NOT IN ('wireguard', 'hysteria2')
          UNION ALL
          SELECT node_id, listen_port, 'udp' AS network
          FROM tbl_configurations
          WHERE protocol IN ('wireguard', 'hysteria2', 'shadowsocks')
        ) bindings GROUP BY node_id, listen_port, network HAVING COUNT(*) > 1
    """)
    )
    if conflicts.first() is not None:
        raise RuntimeError("Resolve overlapping draft ports before upgrading")
    op.alter_column(
        "tbl_configurations",
        "port_network",
        existing_type=sa.String(3),
        type_=sa.String(4),
        existing_nullable=False,
    )
    op.execute(
        "UPDATE tbl_configurations SET port_network='dual' "
        "WHERE protocol='shadowsocks'"
    )
    op.create_table(
        "tbl_inbound_ports",
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
            "configuration_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_configurations.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
        ),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("network", sa.String(3), nullable=False),
        sa.UniqueConstraint(
            "node_id", "port", "network", name="uq_inbound_socket"
        ),
    )
    op.execute("""INSERT INTO tbl_inbound_ports
        (configuration_id, node_id, port, network)
        SELECT id, node_id, listen_port, 'tcp' FROM tbl_configurations
        WHERE port_network IN ('tcp', 'dual')""")
    op.execute("""INSERT INTO tbl_inbound_ports
        (configuration_id, node_id, port, network)
        SELECT id, node_id, listen_port, 'udp' FROM tbl_configurations
        WHERE port_network IN ('udp', 'dual')""")


def downgrade() -> None:
    raise RuntimeError("Restore a backup to roll back transport reservations")
