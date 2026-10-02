from __future__ import annotations

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SetMyName
from aiogram.types import BotDescription, BotName, BotShortDescription

from papilio_proxy.modules.brand.profile.app.services import BrandingService
from papilio_proxy.modules.brand.profile.domain.entities import (
    BotBranding,
    BrandingValidationError,
    validate_branding,
)
from papilio_proxy.modules.brand.profile.infra.telegram import (
    PUBLIC_COMMANDS,
    sync_bot_photo,
    sync_bot_profile,
)
from papilio_proxy.modules.brand.profile.routers.telegram import _branding_text

TEST_BRANDING = BotBranding("Test", "پیش‌نمایش آزمایشی", "پیش‌نمایش؛ فروش هنوز فعال نیست. 📦 📊 🧭")


class BrandingServiceTests(IsolatedAsyncioTestCase):
    async def test_update_persists_only_selected_field(self) -> None:
        repository = AsyncMock()
        repository.get_branding.return_value = TEST_BRANDING
        service = BrandingService(repository)

        updated = await service.update("name", "نام تازه")

        self.assertEqual(updated.name, "نام تازه")
        self.assertEqual(updated.description, TEST_BRANDING.description)
        repository.save_branding.assert_awaited_once_with(updated)

    async def test_overlong_description_is_rejected_before_save(self) -> None:
        repository = AsyncMock()
        repository.get_branding.return_value = TEST_BRANDING
        service = BrandingService(repository)

        with self.assertRaises(BrandingValidationError):
            await service.update("description", "x" * 513)

        repository.save_branding.assert_not_awaited()


class ProfileSyncTests(IsolatedAsyncioTestCase):
    async def test_unchanged_profile_does_not_call_rate_limited_setters(self) -> None:
        bot = AsyncMock(spec=Bot)
        bot.get_my_name.return_value = BotName(name=TEST_BRANDING.name)
        bot.get_my_short_description.return_value = BotShortDescription(
            short_description=TEST_BRANDING.short_description
        )
        bot.get_my_description.return_value = BotDescription(description=TEST_BRANDING.description)
        bot.get_my_commands.return_value = PUBLIC_COMMANDS
        await sync_bot_profile(bot, TEST_BRANDING)
        bot.set_my_name.assert_not_awaited()
        bot.set_my_short_description.assert_not_awaited()
        bot.set_my_description.assert_not_awaited()
        bot.set_my_commands.assert_not_awaited()

    async def test_name_rate_limit_does_not_block_other_fields(self) -> None:
        bot = AsyncMock(spec=Bot)
        bot.set_my_name.side_effect = TelegramRetryAfter(
            method=SetMyName(name=TEST_BRANDING.name), message="limited", retry_after=60
        )
        with self.assertRaises(TelegramRetryAfter):
            await sync_bot_profile(bot, TEST_BRANDING)
        bot.set_my_short_description.assert_awaited_once()
        bot.set_my_description.assert_awaited_once()
        bot.set_my_commands.assert_awaited_once()

    async def test_profile_sync_sets_descriptions_and_real_commands(self) -> None:
        bot = AsyncMock(spec=Bot)

        await sync_bot_profile(bot, TEST_BRANDING)

        bot.set_my_name.assert_awaited_once_with(name=TEST_BRANDING.name)
        bot.set_my_short_description.assert_awaited_once_with(
            short_description=TEST_BRANDING.short_description
        )
        bot.set_my_description.assert_awaited_once_with(description=TEST_BRANDING.description)
        bot.set_my_commands.assert_awaited_once_with(PUBLIC_COMMANDS)
        self.assertEqual(
            [command.command for command in PUBLIC_COMMANDS],
            ["start", "plans", "myservices", "help"],
        )

    async def test_profile_photo_uses_existing_logo(self) -> None:
        bot = AsyncMock(spec=Bot)

        await sync_bot_photo(bot)

        bot.set_my_profile_photo.assert_awaited_once()


class BrandingPresentationTests(TestCase):
    def test_default_profile_is_valid_and_honest(self) -> None:
        validate_branding(TEST_BRANDING)
        self.assertLessEqual(len(TEST_BRANDING.description.encode("utf-16-le")) // 2, 512)
        self.assertLessEqual(len(TEST_BRANDING.short_description.encode("utf-16-le")) // 2, 120)
        self.assertIn("پیش‌نمایش", TEST_BRANDING.description)
        self.assertIn("هنوز فعال نیست", TEST_BRANDING.description)
        for icon in ("📦", "📊", "🧭"):
            self.assertIn(icon, TEST_BRANDING.description)

    def test_admin_preview_escapes_profile_text(self) -> None:
        from papilio_proxy.modules.brand.profile.domain.entities import BotBranding

        preview = _branding_text(BotBranding("<name>", "<short>", "<description>"))

        self.assertIn("&lt;name&gt;", preview)
        self.assertNotIn("<name>", preview)
