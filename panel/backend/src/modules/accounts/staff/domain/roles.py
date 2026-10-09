from enum import StrEnum

from papilio.api.requests.queries import BaseQuery
from papilio.infra.db.schema.entity import BaseEntity, PersistenceEntity
from papilio.infra.db.schema.fields import (
    BoolField,
    CharField,
    ForeignKeyField,
    IntField,
    TextField,
)
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, field_validator

from src.modules.accounts.staff.domain.dtos import StaffScopes


class RoleModel(PersistenceEntity):
    code: str = CharField(64, unique=True)
    title: str = CharField(100)
    is_active: bool = BoolField()
    scopes_json: str = TextField()
    revision: int = IntField(default=1)


class StaffRoleModel(BaseEntity):
    staff_id: int = ForeignKeyField("tbl_staff.id", primary_key=True)
    role_id: int = ForeignKeyField(
        "tbl_staff_roles.id", primary_key=True, index=True
    )


class RoleRevisionModel(PersistenceEntity):
    role_id: int = ForeignKeyField("tbl_staff_roles.id", index=True)
    revision: int = IntField()
    title: str = CharField(100)
    is_active: bool = BoolField()
    scopes_json: str = TextField()
    staff_id: int = ForeignKeyField("tbl_staff.id")
    reason: str = CharField(250)


class StaffRoleChangeModel(PersistenceEntity):
    target_staff_id: int = ForeignKeyField("tbl_staff.id", index=True)
    actor_staff_id: int = ForeignKeyField("tbl_staff.id")
    previous_json: str = TextField()
    current_json: str = TextField()
    reason: str = CharField(250)


class RoleSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class RoleHistorySearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class RoleValues(StaffScopes):
    title: str = Field(min_length=2, max_length=100)
    is_active: bool

    @field_validator("scopes")
    @classmethod
    def no_global_owner(cls, values: list[str]) -> list[str]:
        if "*" in values:
            raise ValueError("Global owner authority requires a direct grant")
        return values


class RoleCreate(RoleValues):
    code: str = Field(
        min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]+$"
    )
    reason: str = Field(min_length=3, max_length=250)


class RoleWrite(RoleValues):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=250)


class RoleAssignmentMode(StrEnum):
    REPLACE = "replace"
    ADD = "add"
    REMOVE = "remove"


class StaffRoleWrite(BaseDTO):
    mode: RoleAssignmentMode
    role_ids: list[int]
    expected_role_ids: list[int]
    reason: str = Field(min_length=3, max_length=250)

    @field_validator("role_ids", "expected_role_ids")
    @classmethod
    def valid_ids(cls, values: list[int]) -> list[int]:
        if len(set(values)) != len(values) or any(
            value < 1 for value in values
        ):
            raise ValueError("Role IDs must be distinct positive identifiers")
        return values
