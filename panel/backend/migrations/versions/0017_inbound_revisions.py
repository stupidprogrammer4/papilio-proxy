"""Version inbound application while preserving legacy profile delivery."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_inbound_revisions"
down_revision: str | None = "0016_durable_fulfillment"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_configurations",
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "tbl_profiles",
        sa.Column("applied_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tbl_provision_tasks",
        sa.Column(
            "configuration_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.execute(
        "UPDATE tbl_profiles p JOIN tbl_configurations c "
        "ON c.id=p.configuration_id SET p.applied_revision=c.revision "
        "WHERE p.applied_generation IS NOT NULL"
    )


def downgrade() -> None:
    raise RuntimeError("Restore a backup to roll back inbound revisions")
