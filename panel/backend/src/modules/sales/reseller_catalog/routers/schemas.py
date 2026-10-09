from datetime import UTC, datetime

from pydantic import field_validator

from src.modules.sales.reseller_catalog.domain.dtos import (
    AgreementFields,
    AgreementPrice,
)
from src.modules.sales.reseller_catalog.domain.models import (
    ResellerPlanChangeModel,
)
from src.modules.sales.reseller_catalog.domain.results import ResellerPlanQuote


class AgreementOut(AgreementFields):
    id: int
    reseller_id: int
    plan_id: int
    revision: int
    code: str
    title: str
    quota_bytes: int | None
    duration_days: int | None
    plan_active: bool
    catalog_price_rial: int
    price_rial: int

    @classmethod
    def from_quote(cls, quote: ResellerPlanQuote) -> "AgreementOut":
        agreement, plan = quote.facts.agreement, quote.facts.plan
        return cls(
            id=agreement.id,
            reseller_id=agreement.reseller_id,
            plan_id=plan.id,
            revision=agreement.revision,
            enabled=agreement.enabled,
            price=AgreementPrice.model_validate_json(agreement.price_json),
            code=plan.code,
            title=plan.title,
            quota_bytes=plan.quota_bytes,
            duration_days=plan.duration_days,
            plan_active=plan.is_active,
            catalog_price_rial=plan.price_rial,
            price_rial=quote.price_rial,
        )


class AgreementChangeOut(AgreementFields):
    id: int
    agreement_id: int
    staff_id: int
    revision: int
    reason: str
    created_at: datetime

    @classmethod
    def from_model(cls, row: ResellerPlanChangeModel) -> "AgreementChangeOut":
        assert row.created_at is not None
        return cls(
            id=row.id,
            agreement_id=row.agreement_id,
            staff_id=row.staff_id,
            revision=row.revision,
            enabled=row.enabled,
            price=AgreementPrice.model_validate_json(row.price_json),
            reason=row.reason,
            created_at=row.created_at,
        )

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
