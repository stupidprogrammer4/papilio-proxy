from collections.abc import Awaitable
from typing import Protocol

from src.modules.bot.domain.dtos import BotLocale
from src.modules.bot.domain.results import BotPresentation


class IBotPresentationQuery(Protocol):
    def get(self, locale: BotLocale) -> Awaitable[BotPresentation]: ...
