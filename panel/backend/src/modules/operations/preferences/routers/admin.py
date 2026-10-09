from datetime import UTC, datetime
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.meta import BaseMeta, PagerMeta
from pydantic import BaseModel, field_validator

from src.modules.accounts.staff.config.dependencies import CurrentStaff, scoped
from src.modules.operations.preferences.domain.dtos import (
    BusinessPreferences,
    PreferencesSearch,
    PreferencesWrite,
)
from src.modules.operations.preferences.domain.results import (
    PreferencesSnapshot,
)
from src.modules.operations.preferences.interfaces import IPreferencesService

router = APIRouter(
    prefix="/v1/admin", tags=["Business settings"], route_class=DishkaRoute
)


class PreferencesRevisionOut(BaseModel):
    revision: int
    values: BusinessPreferences
    changed_by_staff_id: int
    created_at: datetime | None

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )


class BrandingOut(BaseModel):
    brand_title: str


@router.get("/branding")
async def branding(
    principal: CurrentStaff, service: FromDishka[IPreferencesService]
) -> APIResponse[BrandingOut, None]:
    """Read branding for an authenticated operator."""
    result = await service.current()
    return APIResponse.from_data(
        BrandingOut(brand_title=result.values.brand_title)
    )


@router.get("/settings", dependencies=[scoped("settings")])
async def detail(
    service: FromDishka[IPreferencesService],
) -> APIResponse[PreferencesSnapshot, None]:
    """Read current effective business settings."""
    result = await service.current()
    return APIResponse.from_data(result)


@router.put("/settings", dependencies=[scoped("settings")])
async def write(
    data: PreferencesWrite,
    principal: CurrentStaff,
    service: FromDishka[IPreferencesService],
) -> APIResponse[PreferencesSnapshot, None]:
    """Save an audited revision if the displayed version is current."""
    result = await service.write(data, principal.staff_id)
    return APIResponse.from_data(result)


@router.get("/settings/history", dependencies=[scoped("settings")])
async def history(
    data: Annotated[PreferencesSearch, Query()],
    service: FromDishka[IPreferencesService],
) -> APIResponse[PreferencesRevisionOut, BaseMeta]:
    """Read previous values and the operator responsible."""
    result = await service.history(data)
    return APIResponse(
        success=True,
        data=[
            PreferencesRevisionOut(
                revision=row.revision,
                values=BusinessPreferences.model_validate_json(
                    row.values_json
                ),
                changed_by_staff_id=row.changed_by_staff_id,
                created_at=row.created_at,
            )
            for row in result.items
        ],
        meta=BaseMeta(
            pager=PagerMeta.from_total(
                data.page, result.per_page, result.total_items
            )
        ),
    )
