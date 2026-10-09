from datetime import UTC
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta

from src.modules.accounts.staff.config.dependencies import CurrentStaff, scoped
from src.modules.billing.destinations.domain.results import DestinationDetails
from src.modules.billing.sms.interfaces import ISmsService
from src.modules.billing.sms_origins.domain.contracts import (
    DestinationBindingWrite,
    GeneratedParserSample,
    ManualSmsApproval,
    ParserPreviewRead,
    ParserProfileCreate,
    ParserProfileRead,
    ParserProfileUpdate,
    ParserRevisionRead,
    ReceivingAliasRead,
    ReceivingRealmCreate,
    ReceivingRealmRead,
    ReceivingRealmUpdate,
    SmsOriginCapabilities,
    SmsOriginSearch,
    SmsSettlementCandidateRead,
    SmsSettlementReviewRead,
)
from src.modules.billing.sms_origins.interfaces import (
    IReceivingAliasService,
    IReceivingBindingCommand,
    IReceivingRealmCommand,
    IReceivingRealmService,
    ISmsApprovedFundingQuery,
    ISmsOriginCapabilityQuery,
    ISmsOriginQuery,
    ISmsOriginSettlementCommand,
    ISmsParserCommand,
    ISmsSettlementCandidateQuery,
    ISmsSettlementReviewQuery,
)
from src.modules.sales.checkout.interfaces import ICheckoutFundingPublisher

router = APIRouter(
    prefix="/v1/admin/payments/sms-origins",
    tags=["SMS Origins"],
    route_class=DishkaRoute,
)


@router.get("/capabilities", dependencies=[scoped("payments", "read")])
async def capabilities(
    query: FromDishka[ISmsOriginCapabilityQuery],
) -> APIResponse[SmsOriginCapabilities, None]:
    """Read support; declared SMS is not bank attestation."""
    return APIResponse.from_data(query.get())


@router.get("/parser-profiles", dependencies=[scoped("payments", "read")])
async def profiles(
    data: Annotated[SmsOriginSearch, Query()],
    query: FromDishka[ISmsOriginQuery],
) -> APIResponse[ParserProfileRead, BaseMeta]:
    result = await query.profiles_page(data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get(
    "/parser-profiles/{id:int}", dependencies=[scoped("payments", "read")]
)
async def profile(
    id: int, query: FromDishka[ISmsOriginQuery]
) -> APIResponse[ParserProfileRead, None]:
    result = await query.profile(id)
    return APIResponse.from_data(result)


@router.post("/parser-profiles", dependencies=[scoped("payments", "create")])
async def create_profile(
    data: ParserProfileCreate,
    actor: CurrentStaff,
    command: FromDishka[ISmsParserCommand],
) -> APIResponse[ParserProfileRead, None]:
    result = await command.create(data, actor.staff_id)
    return APIResponse.from_data(result)


@router.put(
    "/parser-profiles/{id:int}", dependencies=[scoped("payments", "update")]
)
async def update_profile(
    id: int,
    data: ParserProfileUpdate,
    actor: CurrentStaff,
    command: FromDishka[ISmsParserCommand],
) -> APIResponse[ParserProfileRead, None]:
    result = await command.update(id, data, actor.staff_id)
    return APIResponse.from_data(result)


@router.get(
    "/parser-profiles/{id:int}/revisions",
    dependencies=[scoped("payments", "read")],
)
async def revisions(
    id: int,
    data: Annotated[SmsOriginSearch, Query()],
    query: FromDishka[ISmsOriginQuery],
) -> APIResponse[ParserRevisionRead, BaseMeta]:
    result = await query.revisions_page(id, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get(
    "/parser-profiles/{id:int}/revisions/{revision:int}",
    dependencies=[scoped("payments", "read")],
)
async def revision(
    id: int, revision: int, query: FromDishka[ISmsOriginQuery]
) -> APIResponse[ParserRevisionRead, None]:
    result = await query.revision(id, revision)
    return APIResponse.from_data(result)


@router.post(
    "/parser-profiles/{id:int}/revisions/{revision:int}/sample",
    dependencies=[scoped("payments", "read")],
)
async def sample(
    id: int,
    revision: int,
    data: GeneratedParserSample,
    command: FromDishka[ISmsParserCommand],
) -> APIResponse[ParserPreviewRead, None]:
    result = await command.sample(id, revision, data)
    return APIResponse.from_data(result)


@router.get("/receiving-realms", dependencies=[scoped("payments", "read")])
async def realms(
    data: Annotated[SmsOriginSearch, Query()],
    query: FromDishka[ISmsOriginQuery],
) -> APIResponse[ReceivingRealmRead, BaseMeta]:
    result = await query.realms_page(data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get(
    "/receiving-realms/{id:int}", dependencies=[scoped("payments", "read")]
)
async def realm(
    id: int, query: FromDishka[ISmsOriginQuery]
) -> APIResponse[ReceivingRealmRead, None]:
    result = await query.realm(id)
    return APIResponse.from_data(result)


@router.post("/receiving-realms", dependencies=[scoped("payments", "create")])
async def create_realm(
    data: ReceivingRealmCreate, command: FromDishka[IReceivingRealmCommand]
) -> APIResponse[ReceivingRealmRead, None]:
    result = await command.create(data)
    return APIResponse.from_data(result)


@router.put(
    "/receiving-realms/{id:int}", dependencies=[scoped("payments", "update")]
)
async def update_realm(
    id: int,
    data: ReceivingRealmUpdate,
    command: FromDishka[IReceivingRealmCommand],
) -> APIResponse[ReceivingRealmRead, None]:
    result = await command.update(id, data)
    return APIResponse.from_data(result)


@router.get(
    "/receiving-realms/{realm_id:int}/aliases",
    dependencies=[scoped("payments", "read")],
)
async def aliases_page(
    realm_id: int,
    data: Annotated[SmsOriginSearch, Query()],
    realms: FromDishka[IReceivingRealmService],
    aliases: FromDishka[IReceivingAliasService],
) -> APIResponse[ReceivingAliasRead, BaseMeta]:
    await realms.get(realm_id)
    result = await aliases.search(realm_id, data)
    items = [
        ReceivingAliasRead.model_validate(row, from_attributes=True)
        for row in result.items
    ]
    return APIResponse(
        success=True,
        data=[
            row.model_copy(
                update={"created_at": row.created_at.replace(tzinfo=UTC)}
            )
            for row in items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )


@router.get("/aliases/{id:int}", dependencies=[scoped("payments", "read")])
async def alias(
    id: int, aliases: FromDishka[IReceivingAliasService]
) -> APIResponse[ReceivingAliasRead, None]:
    row = await aliases.get(id)
    result = ReceivingAliasRead.model_validate(row, from_attributes=True)
    return APIResponse.from_data(
        result.model_copy(
            update={"created_at": result.created_at.replace(tzinfo=UTC)}
        )
    )


@router.put(
    "/destinations/{id:int}/receiving-account",
    dependencies=[scoped("payments", "update")],
)
async def bind_destination(
    id: int,
    data: DestinationBindingWrite,
    command: FromDishka[IReceivingBindingCommand],
) -> APIResponse[DestinationDetails, None]:
    result = await command.assign(id, data)
    return APIResponse.from_data(result)


@router.get(
    "/sms-events/{id:int}/review", dependencies=[scoped("payments", "read")]
)
async def settlement_review(
    id: int, query: FromDishka[ISmsSettlementReviewQuery]
) -> APIResponse[SmsSettlementReviewRead, None]:
    result = await query.get(id)
    return APIResponse.from_data(result)


@router.post(
    "/sms-events/{id:int}/review/refresh",
    dependencies=[scoped("payments", "update")],
)
async def refresh_settlement_review(
    id: int,
    messages: FromDishka[ISmsService],
    command: FromDishka[ISmsOriginSettlementCommand],
    funding: FromDishka[ISmsApprovedFundingQuery],
    publisher: FromDishka[ICheckoutFundingPublisher],
    query: FromDishka[ISmsSettlementReviewQuery],
) -> APIResponse[SmsSettlementReviewRead, None]:
    event = await messages.get(id)
    await command.check_event(event.event_id)
    topup_id = await funding.get(id)
    if topup_id is not None:
        await publisher.publish(topup_id)
    result = await query.get(id)
    return APIResponse.from_data(result)


@router.post(
    "/sms-events/{id:int}/approve", dependencies=[scoped("payments", "update")]
)
async def approve_observed_sms(
    id: int,
    data: ManualSmsApproval,
    actor: CurrentStaff,
    messages: FromDishka[ISmsService],
    command: FromDishka[ISmsOriginSettlementCommand],
    funding: FromDishka[ISmsApprovedFundingQuery],
    publisher: FromDishka[ICheckoutFundingPublisher],
    query: FromDishka[ISmsSettlementReviewQuery],
) -> APIResponse[SmsSettlementReviewRead, None]:
    event = await messages.get(id)
    await command.check_event(
        event.event_id,
        expected_topup_id=data.topup_id,
        manual=data,
        staff_id=actor.staff_id,
    )
    topup_id = await funding.get(id)
    if topup_id is not None:
        await publisher.publish(topup_id)
    result = await query.get(id)
    return APIResponse.from_data(result)


@router.get(
    "/sms-events/{id:int}/candidates",
    dependencies=[scoped("payments", "read")],
)
async def settlement_candidates(
    id: int,
    data: Annotated[SmsOriginSearch, Query()],
    query: FromDishka[ISmsSettlementCandidateQuery],
) -> APIResponse[SmsSettlementCandidateRead, BaseMeta]:
    result = await query.get(id, data)
    return APIResponse(
        success=True,
        data=result.items,
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
