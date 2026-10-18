from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class PaymentReceiptModel(PersistenceEntity):
    topup_id: int = ForeignKeyField("tbl_topups.id", index=True)
    content_hash: str = CharField(64)
    media_type: str = CharField(32)
    size_bytes: int = BigIntField()
    encrypted_payload: str = TextField()
    encrypted_extraction: str | None = TextField(default=None)
    ocr_status: str = CharField(16, default="pending")
    annotation_revision: int = IntField(default=0)


class PaymentReceiptAnnotationModel(PersistenceEntity):
    receipt_id: int = ForeignKeyField("tbl_payment_receipts.id", index=True)
    revision: int = IntField()
    staff_id: int = ForeignKeyField("tbl_staff.id")
    encrypted_fields: str = TextField()
    encrypted_reason: str = TextField()
