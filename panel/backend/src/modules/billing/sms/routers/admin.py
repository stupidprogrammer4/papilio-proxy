from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel, Field

from src.modules.accounts.staff.config.dependencies import scoped
from src.modules.billing.sms.domain.dtos import SmsSearch
from src.modules.billing.sms.domain.models import SmsEventModel
from src.modules.billing.sms.interfaces import ISmsCandidateQuery, ISmsService

router = APIRouter(
    prefix="/v1/admin/payments/sms",
    tags=["Admin SMS"],
    route_class=DishkaRoute,
    dependencies=[scoped("payments")],
)


class SmsOut(BaseModel):
    id: int
    event_id: str
    device_id: int | None
    sender: str
    amount_rial: int | None
    bank_reference: str | None
    sent_at: datetime

    parser_revision_id: int | None = None
    parser_definition_sha256: str | None = None
    receiving_realm_id: int | None = None
    receiving_alias_id: int | None = None
    captured_destination_id: int | None = None
    captured_destination_revision: int | None = None
    direction: str | None = None
    parse_reason_code: str | None = None
    balance_rial: int | None = None
    origin_reason_code: str | None = None
    origin_kind: str | None = None
    original_sender: str | None = None
    original_provider_timestamp_ms: int | None = None
    canonicalization_revision: int | None = None
    canonical_message_digest: str | None = None
    origin_identity_sha256: str | None = None
    declared_notification_sha256: str | None = None

    @classmethod
    def from_model(cls, item: SmsEventModel) -> "SmsOut":
        output = cls.model_validate(item, from_attributes=True)
        return output.model_copy(
            update={"sent_at": output.sent_at.replace(tzinfo=UTC)}
        )


class CandidateSearch(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


@router.get("")
async def page(
    data: Annotated[SmsSearch, Query()], service: FromDishka[ISmsService]
) -> APIResponse[SmsOut, BaseMeta]:
    """Review untrusted payment observations without raw SMS content."""
    result = await service.search(data)
    return APIResponse(
        success=True,
        data=[SmsOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/candidates/{topup_id:int}")
async def candidates(
    topup_id: int,
    data: Annotated[CandidateSearch, Query()],
    service: FromDishka[ISmsCandidateQuery],
) -> APIResponse[SmsOut, BaseMeta]:
    """Show same-amount SMS observations for owner review only."""
    result = await service.for_topup(topup_id, data.page, data.per_page)
    return APIResponse(
        success=True,
        data=[SmsOut.from_model(item) for item in result.items],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/{id:int}")
async def detail(
    id: int, service: FromDishka[ISmsService]
) -> APIResponse[SmsOut, None]:
    result = await service.get(id)
    return APIResponse.from_data(SmsOut.from_model(result))
