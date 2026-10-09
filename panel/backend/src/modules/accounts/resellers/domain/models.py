from datetime import datetime

from papilio.infra.db.schema.entity import BaseEntity, PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
    TimestampField,
)

from src.modules.accounts.resellers.domain.dtos import ResellerAccessFields


class ResellerModel(ResellerAccessFields, PersistenceEntity):
    code: str = CharField(64, unique=True)
    title: str = CharField(120)
    wallet_customer_id: int = ForeignKeyField("tbl_customers.id", unique=True)
    revision: int = IntField(default=1)
    access_revision: int = IntField(default=1)
    policy_json: str = TextField()
    created_by_staff_id: int = ForeignKeyField("tbl_staff.id")


class ResellerAccountModel(PersistenceEntity):
    reseller_id: int = ForeignKeyField("tbl_resellers.id", index=True)
    username: str = CharField(64, unique=True)
    password_hash: str = CharField(256)
    is_active: bool = BoolField(default=True)
    revision: int = IntField(default=1)
    scopes_json: str = TextField()


class ResellerSessionModel(BaseEntity):
    token_hash: str = CharField(64, primary_key=True)
    account_id: int = ForeignKeyField("tbl_reseller_accounts.id", index=True)
    reseller_access_revision: int = IntField()
    account_revision: int = IntField()
    csrf_token: str = CharField(64)
    expires_at: datetime = TimestampField(index=True)


class ResellerCustomerModel(BaseEntity):
    customer_id: int = ForeignKeyField("tbl_customers.id", primary_key=True)
    reseller_id: int = ForeignKeyField("tbl_resellers.id", index=True)


class ResellerChangeModel(ResellerAccessFields, PersistenceEntity):
    reseller_id: int = ForeignKeyField("tbl_resellers.id", index=True)
    staff_id: int = ForeignKeyField("tbl_staff.id")
    revision: int = IntField()
    title: str = CharField(120)
    policy_json: str = TextField()
    reason: str = CharField(250)


class ResellerAccountChangeModel(PersistenceEntity):
    reseller_id: int = ForeignKeyField("tbl_resellers.id", index=True)
    account_id: int = ForeignKeyField("tbl_reseller_accounts.id", index=True)
    staff_id: int | None = ForeignKeyField("tbl_staff.id", default=None)
    actor_account_id: int | None = ForeignKeyField(
        "tbl_reseller_accounts.id", default=None
    )
    action: str = CharField(16)
    revision: int = IntField()
    is_active: bool = BoolField()
    scopes_json: str = TextField()
    reason: str = CharField(250)
