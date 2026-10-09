from dataclasses import dataclass
from typing import Literal

from papilio.infra.db.schema.entity import PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
)
from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field

from src.modules.sales.checkout.domain.contracts import CheckoutRead


class CheckoutAttemptModel(PersistenceEntity):
    customer_id: int = ForeignKeyField("tbl_customers.id", index=True)
    request_key: str = CharField(128, unique=True)
    body_sha256: str | None = CharField(64, default=None)
    intent_id: int | None = ForeignKeyField(
        "tbl_checkout_intents.id", default=None, unique=True
    )
    retired: bool = BoolField(default=False)


class CheckoutRetire(BaseDTO):
    request_key: str = Field(min_length=8, max_length=64)


class CheckoutRetirement(BaseModel):
    request_key: str
    status: Literal["retired", "purchased"]
    intent: CheckoutRead | None


@dataclass(frozen=True)
class CheckoutIntentIdentity:
    """Immutable owner/key facts used only to choose the native lock order."""

    customer_id: int
    request_key: str
