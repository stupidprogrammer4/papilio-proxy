from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    CharField,
    ForeignKeyField,
    TextField,
)


class PaymentReceiptModel(PersistenceEntity):
    topup_id: int = ForeignKeyField("tbl_topups.id", index=True)
    content_hash: str = CharField(64)
    media_type: str = CharField(32)
    size_bytes: int = BigIntField()
    encrypted_payload: str = TextField()
