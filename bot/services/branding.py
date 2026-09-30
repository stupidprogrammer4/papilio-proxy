from __future__ import annotations

from dataclasses import replace
from typing import Literal, Protocol

from bot.models.branding import BotBranding, BrandingValidationError, validate_branding

BrandingField = Literal["name", "short_description", "description"]


class BrandingRepository(Protocol):
    async def get_branding(self) -> BotBranding: ...

    async def save_branding(self, branding: BotBranding) -> None: ...


class BrandingService:
    def __init__(self, repository: BrandingRepository) -> None:
        self._repository = repository

    async def get(self) -> BotBranding:
        return await self._repository.get_branding()

    async def update(self, field: BrandingField, value: str) -> BotBranding:
        value = value.strip()
        if field not in {"name", "short_description", "description"}:
            raise BrandingValidationError("فیلد پروفایل معتبر نیست.")
        current = await self._repository.get_branding()
        updated = replace(current, **{field: value})
        validate_branding(updated)
        await self._repository.save_branding(updated)
        return updated
