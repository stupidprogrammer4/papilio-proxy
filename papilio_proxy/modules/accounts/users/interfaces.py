from typing import Protocol


class UserAccessRepository(Protocol):
    async def set_blocked(
        self,
        telegram_id: int,
        blocked: bool,
        reason: str,
        actor: str,
    ) -> list[str]: ...


class AccessRevoker(Protocol):
    async def remove(self, email: str) -> None: ...
