from datetime import UTC, datetime

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header
from papilio.api.responses.envelope import APIResponse
from pydantic import BaseModel, field_validator

from src.modules.network.ip_limits.domain.dtos import IpAdmission
from src.modules.network.ip_limits.interfaces import IIpAdmissionCommand

router = APIRouter(
    prefix="/v1/nodes", tags=["Node IP Admission"], route_class=DishkaRoute
)


class IpDecisionOut(BaseModel):
    subscription_id: int
    source_ip: str
    allowed: bool
    reason: str
    valid_until: datetime
    blocked_until: datetime | None

    @field_validator("valid_until", "blocked_until")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )


@router.post("/{code}/ip-admission")
async def admit(
    code: str,
    data: IpAdmission,
    command: FromDishka[IIpAdmissionCommand],
    x_papilio_node_key: str = Header(default=""),
) -> APIResponse[IpDecisionOut, None]:
    """Authorize a source-IP lease for a subscription assigned to this node."""
    result = await command.admit(code, x_papilio_node_key, data)
    return APIResponse.from_data(
        IpDecisionOut.model_validate(result, from_attributes=True)
    )
