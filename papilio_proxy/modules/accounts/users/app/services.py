from dataclasses import dataclass

from papilio_proxy.modules.accounts.users.domain.entities import UserAccessResult
from papilio_proxy.modules.accounts.users.interfaces import AccessRevoker, UserAccessRepository
from papilio_proxy.modules.network.nodes.app.identity import node_email


@dataclass(slots=True)
class UserAccessService:
    repository: UserAccessRepository
    node: AccessRevoker | None = None

    async def set_blocked(
        self,
        telegram_id: int,
        blocked: bool,
        reason: str,
        actor: str,
    ) -> UserAccessResult:
        reason = reason.strip()
        if not 0 < telegram_id < 2**63 or len(reason) > 300 or not actor:
            raise ValueError("شناسهٔ کاربر یا توضیح مسدودسازی معتبر نیست.")
        # Commit the durable policy first. Failed node calls must not undo the block;
        # reconciliation excludes blocked users and retries orphan removal.
        identifiers = await self.repository.set_blocked(telegram_id, blocked, reason, actor)
        pending = False
        if blocked and identifiers:
            pending = self.node is None
            if self.node is not None:
                for identifier in identifiers:
                    try:
                        await self.node.remove(node_email(identifier))
                    except RuntimeError:
                        pending = True
        return UserAccessResult(telegram_id, blocked, reason, pending)
