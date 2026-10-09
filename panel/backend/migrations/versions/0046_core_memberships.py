"""Preserve explicit immutable installed profile provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision: str = "0046_core_memberships"
down_revision: str | None = "0045_core_runtime"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_core_runtime_revisions",
        sa.Column("encrypted_memberships", LONGTEXT()),
    )
    op.add_column(
        "tbl_core_runtime_revisions",
        sa.Column("membership_sha256", sa.String(64)),
    )
    op.add_column(
        "tbl_core_runtime_commands",
        sa.Column(
            "purpose", sa.String(16), nullable=False, server_default="operator"
        ),
    )
    op.add_column(
        "tbl_core_runtime_states",
        sa.Column(
            "automation_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tbl_core_runtime_states", sa.Column("last_observed_at", sa.DateTime())
    )
    op.add_column(
        "tbl_core_runtime_states",
        sa.Column("last_provision_scan_at", sa.DateTime()),
    )
    op.add_column(
        "tbl_provision_tasks",
        sa.Column("installed_revision_id", sa.BigInteger()),
    )
    op.create_foreign_key(
        "fk_provision_installed_revision",
        "tbl_provision_tasks",
        "tbl_core_runtime_revisions",
        ["installed_revision_id"],
        ["id"],
    )
    op.add_column(
        "tbl_provision_tasks", sa.Column("membership_sha256", sa.String(64))
    )
    op.add_column(
        "tbl_provision_tasks", sa.Column("ack_sha256", sa.String(64))
    )


def downgrade() -> None:
    populated = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM tbl_core_runtime_revisions "
                "WHERE encrypted_memberships IS NOT NULL LIMIT 1"
            )
        )
        .first()
    )
    automatic = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM tbl_core_runtime_commands "
                "WHERE purpose!='operator' LIMIT 1"
            )
        )
        .first()
    )
    provenance = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM tbl_provision_tasks "
                "WHERE installed_revision_id IS NOT NULL "
                "OR membership_sha256 IS NOT NULL "
                "OR ack_sha256 IS NOT NULL LIMIT 1"
            )
        )
        .first()
    )
    paused = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM tbl_core_runtime_states "
                "WHERE automation_paused=1 LIMIT 1"
            )
        )
        .first()
    )
    if any(
        row is not None for row in (populated, automatic, provenance, paused)
    ):
        raise RuntimeError(
            "Restore a backup to preserve installed membership history"
        )
    op.drop_constraint(
        "fk_provision_installed_revision",
        "tbl_provision_tasks",
        type_="foreignkey",
    )
    op.drop_column("tbl_provision_tasks", "ack_sha256")
    op.drop_column("tbl_provision_tasks", "membership_sha256")
    op.drop_column("tbl_provision_tasks", "installed_revision_id")
    op.drop_column("tbl_core_runtime_states", "last_provision_scan_at")
    op.drop_column("tbl_core_runtime_states", "last_observed_at")
    op.drop_column("tbl_core_runtime_states", "automation_paused")
    op.drop_column("tbl_core_runtime_commands", "purpose")
    op.drop_column("tbl_core_runtime_revisions", "membership_sha256")
    op.drop_column("tbl_core_runtime_revisions", "encrypted_memberships")
