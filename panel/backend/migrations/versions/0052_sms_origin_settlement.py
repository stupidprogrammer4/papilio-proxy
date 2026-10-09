"""Revisioned literal parser policies and immutable receiving-origin claims."""

import sqlalchemy as sa
from alembic import op

revision = "0052_sms_origin_settlement"
down_revision = "0051_node_capabilities"
branch_labels = None
depends_on = None


def identity_fields():
    return [
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
    ]


def upgrade():
    op.create_table(
        "tbl_sms_origin_admissions",
        *identity_fields(),
        sa.Column("key", sa.String(32), nullable=False, unique=True),
    )
    op.execute(
        sa.text(
            "INSERT INTO tbl_sms_origin_admissions (`key`) VALUES "
            "('policy_creation'), ('settlement_identity')"
        )
    )
    op.create_table(
        "tbl_receiving_realms",
        *identity_fields(),
        sa.Column("realm_key", sa.String(36), nullable=False, unique=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "origin_requirement_since_ms", sa.BigInteger(), nullable=True
        ),
        sa.Column(
            "origin_mode_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "revision", sa.BigInteger(), nullable=False, server_default="1"
        ),
    )
    op.create_table(
        "tbl_receiving_aliases",
        *identity_fields(),
        sa.Column(
            "realm_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_receiving_realms.id"),
            nullable=False,
        ),
        sa.Column(
            "account_sha256", sa.String(64), nullable=False, unique=True
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("bank_namespace", sa.String(100), nullable=True),
        sa.Column("normalization_revision", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "tbl_sms_parser_profiles",
        *identity_fields(),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "tbl_sms_parser_revisions",
        *identity_fields(),
        sa.Column(
            "profile_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_sms_parser_profiles.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "profile_id", "revision", name="uq_sms_parser_rev"
        ),
    )
    op.add_column(
        "tbl_payment_destinations",
        sa.Column("receiving_alias_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_payment_destinations",
        sa.Column(
            "revision", sa.BigInteger(), nullable=False, server_default="1"
        ),
    )
    op.create_foreign_key(
        "fk_destination_receiving_alias",
        "tbl_payment_destinations",
        "tbl_receiving_aliases",
        ["receiving_alias_id"],
        ["id"],
    )
    op.add_column(
        "tbl_sms_devices",
        sa.Column("parser_profile_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_sms_devices",
        sa.Column(
            "settlement_identity_mode",
            sa.String(32),
            nullable=False,
            server_default="bank_reference_required",
        ),
    )
    op.create_foreign_key(
        "fk_sms_device_parser_profile",
        "tbl_sms_devices",
        "tbl_sms_parser_profiles",
        ["parser_profile_id"],
        ["id"],
    )
    for name, column_type in (
        ("parser_revision_id", sa.BigInteger()),
        ("receiving_realm_id", sa.BigInteger()),
        ("receiving_alias_id", sa.BigInteger()),
        ("captured_destination_id", sa.BigInteger()),
        ("captured_destination_revision", sa.BigInteger()),
        ("direction", sa.String(12)),
        ("parse_reason_code", sa.String(64)),
        ("balance_rial", sa.BigInteger()),
        ("original_provider_timestamp_ms", sa.BigInteger()),
        ("origin_kind", sa.String(24)),
        ("origin_reason_code", sa.String(64)),
        ("original_sender", sa.String(100)),
        ("origin_identity_sha256", sa.String(64)),
        ("declared_notification_sha256", sa.String(64)),
        ("parser_definition_sha256", sa.String(64)),
        ("canonicalization_revision", sa.BigInteger()),
        ("canonical_message_digest", sa.String(64)),
    ):
        op.add_column(
            "tbl_sms_events", sa.Column(name, column_type, nullable=True)
        )
    for column, table in (
        ("parser_revision_id", "tbl_sms_parser_revisions"),
        ("receiving_realm_id", "tbl_receiving_realms"),
        ("receiving_alias_id", "tbl_receiving_aliases"),
        ("captured_destination_id", "tbl_payment_destinations"),
    ):
        op.create_foreign_key(
            "fk_sms_event_" + column, "tbl_sms_events", table, [column], ["id"]
        )
    op.create_index(
        "ix_sms_realm_amount_time",
        "tbl_sms_events",
        ["receiving_realm_id", "amount_rial", "sent_at"],
    )
    for name, target in (
        ("receiving_realm_id", "tbl_receiving_realms"),
        ("receiving_alias_id", "tbl_receiving_aliases"),
    ):
        op.add_column(
            "tbl_topups", sa.Column(name, sa.BigInteger(), nullable=True)
        )
        op.create_foreign_key(
            "fk_topup_" + name, "tbl_topups", target, [name], ["id"]
        )
    op.add_column(
        "tbl_topups",
        sa.Column(
            "captured_destination_revision", sa.BigInteger(), nullable=True
        ),
    )
    op.create_table(
        "tbl_sms_settlements",
        *identity_fields(),
        sa.Column(
            "topup_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_topups.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "sms_event_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_sms_events.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "device_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_sms_devices.id"),
            nullable=False,
        ),
        sa.Column(
            "receiving_realm_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_receiving_realms.id"),
            nullable=False,
        ),
        sa.Column(
            "parser_revision_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_sms_parser_revisions.id"),
            nullable=True,
        ),
        sa.Column("evidence_kind", sa.String(32), nullable=False),
        sa.Column(
            "created_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=True,
        ),
        sa.Column("review_reason", sa.Text(), nullable=True),
    )
    op.create_table(
        "tbl_sms_settlement_claims",
        *identity_fields(),
        sa.Column(
            "settlement_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_sms_settlements.id"),
            nullable=False,
        ),
        sa.Column("identity_kind", sa.String(32), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "identity_kind", "identity_key", name="uq_sms_settlement_identity"
        ),
    )

    op.create_table(
        "tbl_sms_settlement_decisions",
        *identity_fields(),
        sa.Column(
            "sms_event_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_sms_events.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column(
            "candidate_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "topup_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_topups.id"),
            nullable=True,
        ),
        sa.Column(
            "settlement_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_sms_settlements.id"),
            nullable=True,
        ),
    )


def downgrade():
    connection = op.get_bind()
    tables = (
        "tbl_sms_settlement_decisions",
        "tbl_sms_settlement_claims",
        "tbl_sms_settlements",
        "tbl_sms_parser_revisions",
        "tbl_sms_parser_profiles",
        "tbl_receiving_aliases",
        "tbl_receiving_realms",
    )
    populated = any(
        connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table}"))
        for table in tables
    )
    modern_events = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_sms_events WHERE "
            "parser_revision_id IS NOT NULL OR receiving_realm_id IS NOT "
            "NULL OR "
            "receiving_alias_id IS NOT NULL OR captured_destination_id "
            "IS NOT NULL OR "
            "captured_destination_revision IS NOT NULL OR direction IS "
            "NOT NULL OR "
            "parse_reason_code IS NOT NULL OR balance_rial IS NOT NULL OR "
            "origin_kind IS NOT NULL OR origin_reason_code IS NOT NULL OR "
            "original_sender IS NOT NULL OR "
            "origin_identity_sha256 IS NOT NULL OR "
            "declared_notification_sha256 IS NOT NULL OR "
            "parser_definition_sha256 IS NOT NULL OR "
            "original_provider_timestamp_ms IS NOT NULL OR "
            "canonicalization_revision IS NOT NULL OR "
            "canonical_message_digest IS NOT NULL"
        )
    )
    device_policy = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_sms_devices WHERE "
            "parser_profile_id IS NOT NULL "
            "OR settlement_identity_mode <> 'bank_reference_required'"
        )
    )
    destination_policy = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_payment_destinations WHERE "
            "receiving_alias_id IS NOT NULL OR revision <> 1"
        )
    )
    topup_capture = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_topups WHERE receiving_realm_id IS NOT NULL OR receiving_alias_id IS NOT NULL OR captured_destination_revision IS NOT NULL"
        )
    )
    if (
        populated
        or modern_events
        or device_policy
        or destination_policy
        or topup_capture
    ):
        raise RuntimeError(
            "Cannot discard SMS policies or settlement provenance"
        )
    op.drop_table("tbl_sms_settlement_decisions")
    op.drop_table("tbl_sms_settlement_claims")
    op.drop_table("tbl_sms_settlements")
    for column in (
        "parser_revision_id",
        "receiving_realm_id",
        "receiving_alias_id",
        "captured_destination_id",
    ):
        op.drop_constraint(
            "fk_sms_event_" + column, "tbl_sms_events", type_="foreignkey"
        )
    op.drop_index("ix_sms_realm_amount_time", table_name="tbl_sms_events")
    for column in (
        "parser_revision_id",
        "receiving_realm_id",
        "receiving_alias_id",
        "captured_destination_id",
        "captured_destination_revision",
        "direction",
        "parse_reason_code",
        "balance_rial",
        "original_provider_timestamp_ms",
        "origin_kind",
        "origin_reason_code",
        "original_sender",
        "origin_identity_sha256",
        "declared_notification_sha256",
        "parser_definition_sha256",
        "canonicalization_revision",
        "canonical_message_digest",
    ):
        op.drop_column("tbl_sms_events", column)
    op.drop_constraint(
        "fk_sms_device_parser_profile", "tbl_sms_devices", type_="foreignkey"
    )
    op.drop_column("tbl_sms_devices", "parser_profile_id")
    op.drop_column("tbl_sms_devices", "settlement_identity_mode")
    op.drop_constraint(
        "fk_destination_receiving_alias",
        "tbl_payment_destinations",
        type_="foreignkey",
    )
    op.drop_column("tbl_payment_destinations", "receiving_alias_id")
    op.drop_column("tbl_payment_destinations", "revision")
    op.drop_table("tbl_sms_parser_revisions")
    op.drop_table("tbl_sms_parser_profiles")
    op.drop_column("tbl_topups", "captured_destination_revision")
    for name in ("receiving_realm_id", "receiving_alias_id"):
        op.drop_constraint(
            "fk_topup_" + name, "tbl_topups", type_="foreignkey"
        )
        op.drop_column("tbl_topups", name)
    op.drop_table("tbl_receiving_aliases")
    op.drop_table("tbl_receiving_realms")
    op.drop_table("tbl_sms_origin_admissions")
