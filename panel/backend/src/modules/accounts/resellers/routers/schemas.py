from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

from src.modules.accounts.resellers.domain.dtos import (
    ResellerAccessFields,
    ResellerPolicy,
    ResellerScopes,
)
from src.modules.accounts.resellers.domain.models import (
    ResellerAccountChangeModel,
    ResellerAccountModel,
    ResellerChangeModel,
    ResellerModel,
)


class ResellerOut(ResellerAccessFields):
    id: int
    code: str
    title: str
    revision: int
    wallet_customer_id: int
    policy: ResellerPolicy

    @classmethod
    def from_model(cls, row: ResellerModel) -> "ResellerOut":
        return cls(
            id=row.id,
            code=row.code,
            title=row.title,
            revision=row.revision,
            login_enabled=row.login_enabled,
            sales_enabled=row.sales_enabled,
            renewals_enabled=row.renewals_enabled,
            wallet_customer_id=row.wallet_customer_id,
            policy=ResellerPolicy.model_validate_json(row.policy_json),
        )


class ResellerScopeCatalog(BaseModel):
    areas: list[str]
    levels: list[str]


class ResellerAccountOut(ResellerScopes):
    id: int
    reseller_id: int
    username: str
    is_active: bool
    revision: int

    @classmethod
    def from_model(cls, row: ResellerAccountModel) -> "ResellerAccountOut":
        return cls(
            id=row.id,
            reseller_id=row.reseller_id,
            username=row.username,
            is_active=row.is_active,
            revision=row.revision,
            scopes=ResellerScopes.model_validate_json(row.scopes_json).scopes,
        )


class CreatedResellerOut(BaseModel):
    reseller: ResellerOut
    owner: ResellerAccountOut


class ResellerChangeOut(ResellerAccessFields):
    id: int
    reseller_id: int
    staff_id: int
    revision: int
    title: str
    policy: ResellerPolicy
    reason: str
    created_at: datetime

    @classmethod
    def from_model(cls, row: ResellerChangeModel) -> "ResellerChangeOut":
        assert row.created_at is not None
        return cls(
            id=row.id,
            reseller_id=row.reseller_id,
            staff_id=row.staff_id,
            revision=row.revision,
            title=row.title,
            login_enabled=row.login_enabled,
            sales_enabled=row.sales_enabled,
            renewals_enabled=row.renewals_enabled,
            policy=ResellerPolicy.model_validate_json(row.policy_json),
            reason=row.reason,
            created_at=row.created_at,
        )

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ResellerAccountChangeOut(BaseModel):
    id: int
    reseller_id: int
    account_id: int
    staff_id: int | None
    actor_account_id: int | None
    action: str
    revision: int
    is_active: bool
    scopes: list[str]
    reason: str
    created_at: datetime

    @classmethod
    def from_model(
        cls,
        row: ResellerAccountChangeModel,
    ) -> "ResellerAccountChangeOut":
        assert row.created_at is not None
        return cls(
            id=row.id,
            reseller_id=row.reseller_id,
            account_id=row.account_id,
            staff_id=row.staff_id,
            actor_account_id=row.actor_account_id,
            action=row.action,
            revision=row.revision,
            is_active=row.is_active,
            scopes=ResellerScopes.model_validate_json(row.scopes_json).scopes,
            reason=row.reason,
            created_at=row.created_at,
        )

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
