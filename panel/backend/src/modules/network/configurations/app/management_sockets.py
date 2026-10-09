from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts

from src.modules.network.configurations.domain.models import (
    OpenVpnSocketModel,
)
from src.modules.network.configurations.infra.mysql import (
    OpenVpnSocketRepository,
)


class OpenVpnSocketService:
    def __init__(self, repo: OpenVpnSocketRepository) -> None:
        self.repo = repo

    @handle_conflicts(
        message="این سوکت مدیریت روی نود در اختیار ورودی دیگری است.",
        message_code="openvpn_management_conflict",
    )
    async def reserve(self, data: OpenVpnSocketModel) -> OpenVpnSocketModel:
        result = await self.repo.create(data)
        return result

    @handle_conflicts(
        message="این سوکت مدیریت روی نود در اختیار ورودی دیگری است.",
        message_code="openvpn_management_conflict",
    )
    async def change(
        self, configuration_id: int, path: str
    ) -> OpenVpnSocketModel:
        existing = await self.repo.by_configuration(configuration_id, True)
        if existing is None:
            raise self.missing(configuration_id)
        result = await self.repo.update_existing(
            existing, OpenVpnSocketModel.patch(path=path)
        )
        return result

    async def get(self, configuration_id: int) -> OpenVpnSocketModel:
        existing = await self.repo.by_configuration(configuration_id, False)
        if existing is None:
            raise self.missing(configuration_id)
        return existing

    @staticmethod
    def missing(configuration_id: int) -> NotFoundException:
        return NotFoundException(
            message="رزرو سوکت مدیریت این ورودی پیدا نشد.",
            message_code="openvpn_management_missing",
            entity="openvpn_socket",
            identifier="configuration_id",
            identifier_value=configuration_id,
        )
