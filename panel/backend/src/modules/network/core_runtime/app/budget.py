from datetime import timedelta

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.domain.memberships import (
    RuntimeProvisioningBudget,
)
from src.modules.network.core_runtime.infra.budget import (
    RuntimeProvisioningBudgetReader,
)


class CoreProvisioningBudgetQuery:
    def __init__(
        self,
        reader: RuntimeProvisioningBudgetReader,
        settings: PapilioSettings,
    ) -> None:
        self.reader, self.settings = reader, settings

    async def current(
        self, core_id: int, revision_id: int
    ) -> RuntimeProvisioningBudget:
        policy = self.settings.core_provisioning
        if policy is None or policy.mode != "installed_only":
            return RuntimeProvisioningBudget(exhausted=True)
        successful_id = await self.reader.latest_success(
            core_id,
            revision_id,
            ["apply", "restart", "rollback"],
            "reconcile",
            "restore",
            ["succeeded"],
            1,
        )
        attempts = await self.reader.attempts(
            core_id,
            revision_id,
            "provisioning",
            ["apply", "restart", "rollback"],
            "reconcile",
            "restore",
            successful_id,
            1,
            policy.max_attempts + 1,
        )
        consumed = sum(item.attempts for item in attempts)
        retry_at = (
            attempts[0].updated_at + timedelta(seconds=policy.retry_seconds)
            if attempts
            else None
        )
        return RuntimeProvisioningBudget(
            exhausted=consumed >= policy.max_attempts,
            retry_at=retry_at,
        )
