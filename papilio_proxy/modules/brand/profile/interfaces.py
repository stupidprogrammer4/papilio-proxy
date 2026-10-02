from typing import Protocol

from papilio_proxy.modules.brand.profile.domain.entities import BotBranding


class BrandingRepository(Protocol):
    async def get_branding(self) -> BotBranding: ...

    async def save_branding(self, branding: BotBranding) -> None: ...
