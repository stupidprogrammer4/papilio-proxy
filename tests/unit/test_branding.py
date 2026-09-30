from __future__ import annotations

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from aiogram import Bot

from bot.models.branding import DEFAULT_BRANDING, BrandingValidationError
from bot.presentation.admin_branding import _branding_text
from bot.presentation.profile import PUBLIC_COMMANDS, sync_bot_photo, sync_bot_profile
from bot.services.branding import BrandingService


class BrandingServiceTests(IsolatedAsyncioTestCase):
    async def test_update_persists_only_selected_field(self) -> None:
        repository = AsyncMock()
        repository.get_branding.return_value = DEFAULT_BRANDING
        service = BrandingService(repository)

        updated = await service.update("name", "نام تازه")

        self.assertEqual(updated.name, "نام تازه")
        self.assertEqual(updated.description, DEFAULT_BRANDING.description)
        repository.save_branding.assert_awaited_once_with(updated)

    async def test_overlong_description_is_rejected_before_save(self) -> None:
        repository = AsyncMock()
        repository.get_branding.return_value = DEFAULT_BRANDING
        service = BrandingService(repository)

        with self.assertRaises(BrandingValidationError):
            await service.update("description", "x" * 513)

        repository.save_branding.assert_not_awaited()


class ProfileSyncTests(IsolatedAsyncioTestCase):
    async def test_profile_sync_sets_descriptions_and_real_commands(self) -> None:
        bot = AsyncMock(spec=Bot)

        await sync_bot_profile(bot, DEFAULT_BRANDING)

        bot.set_my_name.assert_awaited_once_with(name=DEFAULT_BRANDING.name)
        bot.set_my_short_description.assert_awaited_once_with(
            short_description=DEFAULT_BRANDING.short_description
        )
        bot.set_my_description.assert_awaited_once_with(description=DEFAULT_BRANDING.description)
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
    def test_admin_preview_escapes_profile_text(self) -> None:
        from bot.models.branding import BotBranding

        preview = _branding_text(BotBranding("<name>", "<short>", "<description>"))

        self.assertIn("&lt;name&gt;", preview)
        self.assertNotIn("<name>", preview)
