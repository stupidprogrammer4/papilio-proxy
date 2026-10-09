"""Save revisioned client balancing choices without storing credentials."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_balancer_policies"
down_revision: str | None = "0041_notification_lease_index"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_balancer_policies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column("group_id", sa.BigInteger(),
                  sa.ForeignKey("tbl_host_groups.id"), nullable=False),
        sa.Column("client_core", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("group_id", "client_core",
                            name="uq_balancer_group_core"),
    )


def downgrade() -> None:
    if op.get_bind().execute(
        sa.text("SELECT 1 FROM tbl_balancer_policies LIMIT 1")
    ).first() is not None:
        raise RuntimeError("Restore a backup to preserve balancing policies")
    op.drop_table("tbl_balancer_policies")
