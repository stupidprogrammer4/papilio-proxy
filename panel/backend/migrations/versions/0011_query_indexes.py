"""Match endpoint-probe joins and pending-payment pagination."""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_query_indexes"
down_revision: str | None = "0010_configurations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_probe_node_network_time",
        "tbl_probes",
        ["node_id", "client_network", "sampled_at"],
    )
    op.drop_index("ix_probe_network_time_node", table_name="tbl_probes")
    op.create_index("ix_topup_status_id", "tbl_topups", ["status", "id"])


def downgrade() -> None:
    op.drop_index("ix_topup_status_id", table_name="tbl_topups")
    op.create_index(
        "ix_probe_network_time_node",
        "tbl_probes",
        ["client_network", "sampled_at", "node_id"],
    )
    op.drop_index("ix_probe_node_network_time", table_name="tbl_probes")
