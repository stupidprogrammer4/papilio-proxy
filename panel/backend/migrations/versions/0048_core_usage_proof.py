"""Immutable runtime usage capabilities and process-bound native grants."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "0048_core_usage_proof"
down_revision = "0047_subscription_notice_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_core_runtime_revisions",
        sa.Column("encrypted_usage", LONGTEXT(), nullable=True),
    )
    op.add_column(
        "tbl_core_runtime_revisions",
        sa.Column("usage_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "tbl_core_runtime_states",
        sa.Column("observed_process_epoch", sa.String(128), nullable=True),
    )
    op.add_column(
        "tbl_usage_grants",
        sa.Column("installed_revision_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_usage_grants",
        sa.Column("usage_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "tbl_usage_grants",
        sa.Column("process_epoch", sa.String(128), nullable=True),
    )
    op.create_foreign_key(
        "fk_usage_installed_revision",
        "tbl_usage_grants",
        "tbl_core_runtime_revisions",
        ["installed_revision_id"],
        ["id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    if (
        connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM tbl_core_runtime_revisions "
                "WHERE encrypted_usage IS NOT NULL OR usage_sha256 IS NOT NULL"
            )
        ).scalar_one()
        or connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM tbl_usage_grants "
                "WHERE installed_revision_id IS NOT NULL "
                "OR usage_sha256 IS NOT NULL OR process_epoch IS NOT NULL"
            )
        ).scalar_one()
        or connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM tbl_core_runtime_states "
                "WHERE observed_process_epoch IS NOT NULL"
            )
        ).scalar_one()
    ):
        raise RuntimeError(
            "Runtime usage provenance must be preserved before downgrade"
        )
    op.drop_constraint(
        "fk_usage_installed_revision", "tbl_usage_grants", type_="foreignkey"
    )
    op.drop_column("tbl_usage_grants", "process_epoch")
    op.drop_column("tbl_usage_grants", "usage_sha256")
    op.drop_column("tbl_usage_grants", "installed_revision_id")
    op.drop_column("tbl_core_runtime_states", "observed_process_epoch")
    op.drop_column("tbl_core_runtime_revisions", "usage_sha256")
    op.drop_column("tbl_core_runtime_revisions", "encrypted_usage")
