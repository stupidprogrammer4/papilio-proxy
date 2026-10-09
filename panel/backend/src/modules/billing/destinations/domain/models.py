from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)


class PaymentDestinationModel(PersistenceEntity):
    title: str = CharField(100)
    kind: str = CharField(24)
    encrypted_details: str = TextField()
    is_active: bool = BoolField(default=False, index=True)

    receiving_alias_id: int | None = ForeignKeyField(
        "tbl_receiving_aliases.id", default=None
    )
    revision: int = IntField(default=1)
