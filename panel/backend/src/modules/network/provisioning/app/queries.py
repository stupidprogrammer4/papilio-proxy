from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import NotFoundException

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.provisioning.domain.dtos import ProvisioningSearch
from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.network.provisioning.infra.mysql import (
    ProvisionRequestRepository,
    ProvisionTaskRepository,
)
from src.modules.network.provisioning.infra.readers import (
    ProvisioningFactsReader,
)
from src.modules.operations.automation.domain.dtos import ScheduleKey
from src.modules.operations.automation.interfaces import IAutomationPolicyQuery


class ProvisioningQuery:
    def __init__(
        self,
        requests: ProvisionRequestRepository,
        tasks: ProvisionTaskRepository,
        nodes: INodeService,
        settings: PapilioSettings,
        automation: IAutomationPolicyQuery,
        facts: ProvisioningFactsReader,
    ) -> None:
        self.request_repo = requests
        self.task_repo = tasks
        self.nodes = nodes
        self.settings = settings
        self.automation = automation
        self.facts = facts

    async def due_ids(self) -> list[int]:
        current = await self.automation.schedule(ScheduleKey.PROVISIONING)
        if not current.runnable:
            return []
        schedule = current.values
        assert schedule.recheck_seconds is not None
        before = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            seconds=schedule.recheck_seconds
        )
        result = await self.request_repo.due_ids(
            before,
            [
                "queued",
                "awaiting_profiles",
                "dispatching",
                "active",
                "revoking",
            ],
            schedule.batch_size,
        )
        return result

    async def requests(
        self, data: ProvisioningSearch
    ) -> ServicePage[ProvisionRequestModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.request_repo.page(
            data.subscription_id, data.state, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)

    async def tasks(
        self, request_id: int, data: ProvisioningSearch
    ) -> ServicePage[ProvisionTaskModel]:
        request = await self.request_repo.get_by_id(request_id)
        if request is None:
            raise NotFoundException(
                message="درخواست راه‌اندازی پیدا نشد.",
                message_code="provision_request_not_found",
                entity="provision_request",
                identifier="id",
                identifier_value=request_id,
            )
        limit = page_size(self.settings, data.per_page)
        result = await self.task_repo.page(
            request_id,
            data.node_id,
            [data.state] if data.state is not None else None,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)

    async def node_tasks(
        self, code: str, key: str, data: ProvisioningSearch
    ) -> ServicePage[ProvisionTaskModel]:
        node = await self.nodes.authenticate(code, key)
        limit = page_size(self.settings, data.per_page)
        result = await self.facts.node_tasks(
            node.id,
            data.core_id,
            ["queued", "failed", "leased"],
            ["dispatching", "active", "revoking"],
            datetime.now(UTC).replace(tzinfo=None, microsecond=0)
            if data.actionable
            else None,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)
