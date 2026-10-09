from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BigIntField,
    CharField,
    ForeignKeyField,
)


class PaymentAmountReservationModel(PersistenceEntity):
    receiving_realm_id: int = ForeignKeyField("tbl_receiving_realms.id")
    topup_id: int = ForeignKeyField("tbl_topups.id", unique=True)
    requested_amount_rial: int = BigIntField()
    payable_amount_rial: int = BigIntField()
    code4: str = CharField(4)
