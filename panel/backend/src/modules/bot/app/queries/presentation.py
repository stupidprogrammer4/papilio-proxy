from src.modules.bot.app.helpers.presentation import presentation_from_settings
from src.modules.bot.app.interfaces import IBotPresentationQuery
from src.modules.bot.domain.dtos import BotLocale
from src.modules.bot.domain.results import BotPresentation
from src.modules.operations.preferences.interfaces import IPreferencesService


class BotPresentationQuery(IBotPresentationQuery):
    def __init__(self, preferences: IPreferencesService) -> None:
        self.preferences = preferences

    async def get(self, locale: BotLocale) -> BotPresentation:
        snapshot = await self.preferences.current()
        result = presentation_from_settings(
            snapshot.values.bot_presentation, locale
        )
        return result
