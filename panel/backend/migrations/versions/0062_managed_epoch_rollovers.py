"""Persist exact managed epoch rollover identity."""

import sqlalchemy as sa
from alembic import op

revision = "0062_managed_epoch_rollovers"
down_revision = "0061_managed_epoch_seals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_managed_epoches",
        sa.Column("previous_epoch_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_managed_epoches",
        sa.Column("rollover_request_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "tbl_managed_epoches",
        sa.Column("rollover_request_sha256", sa.String(64), nullable=True),
    )
    op.create_foreign_key(
        "fk_managed_epoch_previous",
        "tbl_managed_epoches",
        "tbl_managed_epoches",
        ["previous_epoch_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_managed_epoch_successor",
        "tbl_managed_epoches",
        ["previous_epoch_id"],
    )
    op.create_unique_constraint(
        "uq_managed_epoch_rollover_request",
        "tbl_managed_epoches",
        ["rollover_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_managed_epoch_previous",
        "tbl_managed_epoches",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_managed_epoch_rollover_request",
        "tbl_managed_epoches",
        type_="unique",
    )
    op.drop_constraint(
        "uq_managed_epoch_successor",
        "tbl_managed_epoches",
        type_="unique",
    )
    op.drop_column("tbl_managed_epoches", "rollover_request_sha256")
    op.drop_column("tbl_managed_epoches", "rollover_request_id")
    op.drop_column("tbl_managed_epoches", "previous_epoch_id")
