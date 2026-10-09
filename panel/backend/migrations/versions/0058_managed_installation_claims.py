"""Native CLOSED installation leases; no paid admission authority."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0058_managed_installation_claims"
down_revision = "0057_ip_session_precision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    canonical_exists = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema=DATABASE() AND "
                "table_name='tbl_managed_epoches'"
            )
        )
        .scalar_one()
    )
    if canonical_exists:
        raise RuntimeError(
            "Resolve conflicting native managed epoch table first"
        )
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT process_epoch FROM tbl_managed_epochs "
                "GROUP BY process_epoch HAVING COUNT(*)>1)"
            )
        )
        .scalar_one()
    )
    if duplicate:
        raise RuntimeError("Resolve legacy duplicate managed epochs first")
    op.add_column(
        "tbl_managed_installations",
        sa.Column(
            "state",
            sa.String(16),
            nullable=False,
            server_default="legacy_unknown",
        ),
    )
    op.alter_column(
        "tbl_managed_installations",
        "state",
        existing_type=sa.String(16),
        existing_nullable=False,
        server_default="issued",
    )
    op.add_column(
        "tbl_managed_installations",
        sa.Column("claim_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "tbl_managed_installations",
        sa.Column("claim_until", DATETIME(fsp=6), nullable=True),
    )
    op.add_column(
        "tbl_managed_installations",
        sa.Column("acknowledgement_sha256", sa.String(64), nullable=True),
    )
    op.rename_table("tbl_managed_epochs", "tbl_managed_epoches")
    op.create_unique_constraint(
        "uq_managed_process_epoch", "tbl_managed_epoches", ["process_epoch"]
    )


def downgrade() -> None:
    active = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM tbl_managed_installations "
                "WHERE claim_hash IS NOT NULL"
            )
        )
        .scalar_one()
    )
    if active:
        raise RuntimeError("Cannot discard native managed installation claims")
    op.drop_constraint(
        "uq_managed_process_epoch", "tbl_managed_epoches", type_="unique"
    )
    op.rename_table("tbl_managed_epoches", "tbl_managed_epochs")
    op.drop_column("tbl_managed_installations", "acknowledgement_sha256")
    op.drop_column("tbl_managed_installations", "claim_until")
    op.drop_column("tbl_managed_installations", "claim_hash")
    op.drop_column("tbl_managed_installations", "state")
