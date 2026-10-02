from collections.abc import AsyncIterator

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dishka import Provider, Scope, provide
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork

from papilio_proxy.config.database import DatabaseConnection
from papilio_proxy.config.settings import ConfigurationError, Settings


class RuntimeProvider(Provider):
    scope = Scope.APP

    def __init__(self, settings: Settings | None) -> None:
        super().__init__()
        self._settings = settings

    @provide
    def settings(self) -> Settings:
        if self._settings is None:
            raise ConfigurationError("تنظیمات محیط برنامه کامل نیست.")
        return self._settings

    @provide
    async def database(self, settings: Settings) -> AsyncIterator[DatabaseConnection]:
        database = DBConnection(
            dsn=settings.database_url,
            pool_size=5,
            max_overflow=5,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        database.engine.sync_engine.hide_parameters = True
        try:
            yield database
        finally:
            await database.dispose()

    @provide
    async def bot(self, settings: Settings) -> AsyncIterator[Bot]:
        if settings.bot_token is None:
            raise ConfigurationError("توکن بات تنظیم نشده است.")
        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            yield bot
        finally:
            await bot.session.close()
