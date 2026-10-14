from datetime import datetime

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)


class ReceivingRealmModel(PersistenceEntity):
    realm_key: str = CharField(36, unique=True)
    title: str = CharField(100)
    is_active: bool = BoolField()
    revision: int = IntField(default=1)
    origin_mode_enabled: bool = BoolField(default=False)
    origin_requirement_since_ms: int | None = BigIntField(default=None)


class ReceivingAliasModel(PersistenceEntity):
    realm_id: int = ForeignKeyField("tbl_receiving_realms.id", index=True)
    account_sha256: str = CharField(64, unique=True)
    kind: str = CharField(24)
    bank_namespace: str | None = CharField(100, default=None)
    normalization_revision: int = IntField(default=1)


class SmsParserProfileModel(PersistenceEntity):
    title: str = CharField(100)
    is_active: bool = BoolField()
    revision: int = IntField(default=1)


class SmsParserRevisionModel(PersistenceEntity):
    profile_id: int = ForeignKeyField("tbl_sms_parser_profiles.id", index=True)
    revision: int = IntField()
    definition_json: str = TextField()
    definition_sha256: str = CharField(64)
    created_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )


class SmsSettlementModel(PersistenceEntity):
    topup_id: int = ForeignKeyField("tbl_topups.id", unique=True)
    sms_event_id: int = ForeignKeyField("tbl_sms_events.id", unique=True)
    device_id: int = ForeignKeyField("tbl_sms_devices.id")
    receiving_realm_id: int = ForeignKeyField(
        "tbl_receiving_realms.id", index=True
    )
    parser_revision_id: int | None = ForeignKeyField(
        "tbl_sms_parser_revisions.id", default=None
    )
    evidence_kind: str = CharField(32)
    created_by_staff_id: int | None = ForeignKeyField(
        "tbl_staff.id", default=None
    )
    review_reason: str | None = TextField(default=None)


class SmsSettlementClaimModel(PersistenceEntity):
    settlement_id: int = ForeignKeyField("tbl_sms_settlements.id", index=True)
    identity_kind: str = CharField(32)
    identity_key: str = CharField(64)


class SmsOriginAdmissionModel(PersistenceEntity):
    key: str = CharField(32, unique=True)


class SmsSettlementDecisionModel(PersistenceEntity):
    sms_event_id: int = ForeignKeyField("tbl_sms_events.id", index=True)
    status: str = CharField(24)
    reason_code: str | None = CharField(64, default=None)
    checked_at: datetime = TimestampField()
    candidate_count: int = IntField(default=0)
    topup_id: int | None = ForeignKeyField("tbl_topups.id", default=None)
    settlement_id: int | None = ForeignKeyField(
        "tbl_sms_settlements.id", default=None
    )
