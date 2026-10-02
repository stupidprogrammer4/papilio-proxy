from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BotBranding:
    name: str
    short_description: str
    description: str


class BrandingValidationError(ValueError):
    """A profile field exceeds Telegram's limits or contains invalid text."""


def validate_branding(branding: BotBranding) -> None:
    fields = (
        ("نام", branding.name, 64),
        ("توضیح کوتاه", branding.short_description, 120),
        ("توضیح کامل", branding.description, 512),
    )
    for label, value, maximum in fields:
        if not value.strip() or len(value) > maximum or "\x00" in value:
            raise BrandingValidationError(f"{label} باید بین ۱ تا {maximum} نویسه باشد.")
