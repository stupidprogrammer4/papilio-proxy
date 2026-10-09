"""Reserve private management endpoints before core application."""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from papilio.core.config import get_settings
from papilio.security.crypto import decrypt

from src.config.settings import PapilioSettings
from src.modules.network.configurations.domain.openvpn import OpenVpnOptions

revision: str = "0036_openvpn_management_sockets"
down_revision: str | None = "0035_reseller_customer_access"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id,node_id,encrypted_settings FROM tbl_configurations "
            "WHERE protocol='openvpn' ORDER BY id"
        )
    )
    key = get_settings(PapilioSettings).configuration_encryption_key
    bindings: set[tuple[int, str]] = set()
    reservations: list[dict[str, int | str]] = []
    for row in rows:
        raw = json.loads(decrypt(row.encrypted_settings, key))
        options = OpenVpnOptions.model_validate(raw["options"])
        binding = (row.node_id, options.management_socket)
        if binding in bindings:
            raise RuntimeError(
                "Resolve overlapping OpenVPN management sockets "
                "before upgrading"
            )
        bindings.add(binding)
        reservations.append(
            {
                "configuration_id": row.id,
                "node_id": row.node_id,
                "path": options.management_socket,
            }
        )
    table = op.create_table(
        "tbl_open_vpn_sockets",
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
            unique=True,
        ),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
        ),
        sa.Column(
            "path", sa.String(255, collation="ascii_bin"), nullable=False
        ),
        sa.UniqueConstraint("node_id", "path", name="uq_openvpn_management"),
    )
    if reservations:
        op.bulk_insert(table, reservations)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM tbl_open_vpn_sockets"))
        .scalar_one()
    ):
        raise RuntimeError(
            "Restore a backup rather than remove active management ownership"
        )
    op.drop_table("tbl_open_vpn_sockets")
