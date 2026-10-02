from __future__ import annotations

from dataclasses import replace
from typing import Literal

from papilio_proxy.modules.brand.profile.domain.entities import (
    BotBranding,
    BrandingValidationError,
    validate_branding,
)

BrandingField = Literal["name", "short_description", "description"]


from papilio_proxy.modules.brand.profile.interfaces import BrandingRepository


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
        # A fresh installation is filled field by field, without seeded copy.
        if all((updated.name, updated.short_description, updated.description)):
            validate_branding(updated)
        elif (
            not value
            or len(value) > {"name": 64, "short_description": 120, "description": 512}[field]
        ):
            raise BrandingValidationError("طول متن پروفایل معتبر نیست.")
        await self._repository.save_branding(updated)
        return updated
