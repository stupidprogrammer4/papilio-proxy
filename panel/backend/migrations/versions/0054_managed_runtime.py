"""Immutable managed authority storage; activation remains unavailable."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME, LONGTEXT

revision = "0054_managed_runtime"
down_revision = "0053_payment_amount_identifiers"
branch_labels = None
depends_on = None


def _identity_columns() -> tuple[sa.Column, ...]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "tbl_managed_installations",
        *_identity_columns(),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
        ),
        sa.Column(
            "core_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_cores.id"),
            nullable=False,
        ),
        sa.Column(
            "runtime_revision_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_core_runtime_revisions.id"),
            nullable=False,
        ),
        sa.Column("installation_sha256", sa.String(64), nullable=False),
        sa.Column("encrypted_manifest", LONGTEXT(), nullable=False),
        sa.UniqueConstraint(
            "core_id",
            "runtime_revision_id",
            "installation_sha256",
            name="uq_managed_installation_identity",
        ),
    )
    op.create_table(
        "tbl_managed_epochs",
        *_identity_columns(),
        sa.Column(
            "installation_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_installations.id"),
            nullable=False,
        ),
        sa.Column("process_epoch", sa.String(32), nullable=False),
        sa.Column("installed_closed_at", DATETIME(fsp=6), nullable=False),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column("encrypted_receipt", LONGTEXT(), nullable=False),
        sa.UniqueConstraint(
            "installation_id",
            "process_epoch",
            name="uq_managed_epoch_identity",
        ),
    )
    op.create_table(
        "tbl_managed_barriers",
        *_identity_columns(),
        sa.Column(
            "epoch_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_epochs.id"),
            nullable=False,
        ),
        sa.Column("barrier_id", sa.String(32), nullable=False),
        sa.Column("acceptance_id", sa.String(32), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("frozen_at", DATETIME(fsp=6), nullable=False),
        sa.Column("accepted_at", DATETIME(fsp=6), nullable=False),
        sa.Column("encrypted_receipt", LONGTEXT(), nullable=False),
        sa.UniqueConstraint(
            "epoch_id", "barrier_id", name="uq_managed_barrier_identity"
        ),
        sa.UniqueConstraint(
            "acceptance_id", name="uq_managed_barrier_acceptance"
        ),
    )
    op.create_table(
        "tbl_managed_windows",
        *_identity_columns(),
        sa.Column(
            "epoch_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_epochs.id"),
            nullable=False,
        ),
        sa.Column(
            "grant_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_usage_grants.id"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
        ),
        sa.Column(
            "provision_task_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_provision_tasks.id"),
            nullable=True,
        ),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("window_id", sa.String(32), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("window_sha256", sa.String(64), nullable=False),
        sa.Column("baseline_upload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("baseline_download_bytes", sa.BigInteger(), nullable=False),
        sa.Column("allocated_bytes", sa.BigInteger(), nullable=False),
        sa.Column("issued_at", DATETIME(fsp=6), nullable=False),
        sa.Column("valid_until", DATETIME(fsp=6), nullable=False),
        sa.Column(
            "predecessor_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_barriers.id"),
            nullable=True,
        ),
        sa.Column("encrypted_window", LONGTEXT(), nullable=False),
        sa.UniqueConstraint("grant_id", name="uq_managed_window_grant"),
        sa.UniqueConstraint("window_id", name="uq_managed_window_identity"),
        sa.UniqueConstraint(
            "profile_id",
            "generation",
            "request_key",
            name="uq_managed_window_request",
        ),
    )
    op.create_table(
        "tbl_managed_admissions",
        *_identity_columns(),
        sa.Column(
            "window_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_managed_windows.id"),
            nullable=False,
        ),
        sa.Column(
            "provision_task_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_provision_tasks.id"),
            nullable=False,
        ),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("observed_at", DATETIME(fsp=6), nullable=False),
        sa.Column("encrypted_receipt", LONGTEXT(), nullable=False),
        sa.UniqueConstraint("window_id", name="uq_managed_admission_window"),
    )


def downgrade() -> None:
    tables = (
        "tbl_managed_admissions",
        "tbl_managed_windows",
        "tbl_managed_barriers",
        "tbl_managed_epochs",
        "tbl_managed_installations",
    )
    connection = op.get_bind()
    for table in tables:
        if connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError(
                "Downgrade would lose managed authority receipts"
            )
    for table in tables:
        op.drop_table(table)
