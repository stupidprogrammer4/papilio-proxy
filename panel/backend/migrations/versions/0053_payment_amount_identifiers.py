"""Immutable payable rial amounts and four-digit invoice identifiers."""

import sqlalchemy as sa
from alembic import op

revision = "0053_payment_amount_identifiers"
down_revision = "0052_sms_origin_settlement"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tbl_topups",
        sa.Column("requested_amount_rial", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_topups",
        sa.Column(
            "payment_identifier_mode",
            sa.String(24),
            nullable=False,
            server_default="exact_requested",
        ),
    )
    op.add_column(
        "tbl_topups",
        sa.Column("payment_identifier_code4", sa.String(4), nullable=True),
    )
    op.create_index(
        "ix_topup_realm_amount",
        "tbl_topups",
        ["receiving_realm_id", "amount_rial"],
    )
    op.create_index(
        "ix_topup_realm_status_amount",
        "tbl_topups",
        ["receiving_realm_id", "status", "amount_rial"],
    )
    op.create_table(
        "tbl_payment_amount_reservations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "receiving_realm_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_receiving_realms.id"),
            nullable=False,
        ),
        sa.Column(
            "topup_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_topups.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("requested_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("payable_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("code4", sa.String(4), nullable=False),
        sa.UniqueConstraint(
            "receiving_realm_id",
            "payable_amount_rial",
            name="uq_payment_reserved_realm_amount",
        ),
    )


def downgrade():
    connection = op.get_bind()
    modern = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_topups WHERE "
            "requested_amount_rial IS NOT NULL OR "
            "payment_identifier_mode <> 'exact_requested' OR "
            "payment_identifier_code4 IS NOT NULL"
        )
    )
    reservations = connection.scalar(
        sa.text("SELECT COUNT(*) FROM tbl_payment_amount_reservations")
    )
    if modern or reservations:
        raise RuntimeError("Cannot discard issued payable amount identities")
    indexes = sa.inspect(connection).get_indexes("tbl_topups")
    realm_index = "fk_topup_receiving_realm_id"
    if not any(index["name"] == realm_index for index in indexes):
        op.create_index(realm_index, "tbl_topups", ["receiving_realm_id"])
    op.drop_table("tbl_payment_amount_reservations")
    op.drop_index("ix_topup_realm_status_amount", table_name="tbl_topups")
    op.drop_index("ix_topup_realm_amount", table_name="tbl_topups")
    op.drop_column("tbl_topups", "payment_identifier_code4")
    op.drop_column("tbl_topups", "payment_identifier_mode")
    op.drop_column("tbl_topups", "requested_amount_rial")
