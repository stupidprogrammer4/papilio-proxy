"""Preserve immutable paid window claims across task lease replacement."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME, LONGTEXT

revision = "0059_managed_provision_claims"
down_revision = "0058_managed_installation_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_managed_windows",
        sa.Column("encrypted_provision_claim", sa.Text(), nullable=True),
    )
    op.create_table(
        "tbl_managed_revocations",
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
            "window_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_windows.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "provision_task_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_provision_tasks.id"),
            nullable=False,
        ),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column("observed_at", DATETIME(fsp=6), nullable=False),
        sa.Column("encrypted_receipt", LONGTEXT(), nullable=False),
    )


def downgrade() -> None:
    claims = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT id FROM tbl_managed_windows "
                "WHERE encrypted_provision_claim IS NOT NULL)"
            )
        )
        .scalar_one()
    )
    if claims:
        raise RuntimeError("Cannot discard immutable paid managed claims")
    revocations = (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT id FROM tbl_managed_revocations)")
        )
        .scalar_one()
    )
    if revocations:
        raise RuntimeError("Cannot discard managed revocation evidence")
    op.drop_table("tbl_managed_revocations")
    op.drop_column("tbl_managed_windows", "encrypted_provision_claim")
