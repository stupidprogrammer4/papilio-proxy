from dishka import Provider, Scope, alias
from papilio.core.bootstrap import Bootstrapper
from papilio.core.config import Settings
from papilio.providers.base import CoreProvider
from papilio.providers.db import MySQLProvider
from papilio.providers.rate_limit.redis import RedisRateProvider
from papilio.providers.redis import RedisProvider

from src.config.settings import PapilioSettings


class SettingsProvider(Provider):
    scope = Scope.APP
    application_settings = alias(Settings, provides=PapilioSettings)


def infrastructure_providers(settings: PapilioSettings) -> list[Provider]:
    if settings.db is None:
        raise RuntimeError("Configure db in config.yml")
    providers: list[Provider] = [
        MySQLProvider(settings.db),
        SettingsProvider(),
    ]
    if settings.redis is not None:
        providers.extend([RedisProvider(settings.redis), RedisRateProvider()])
    elif settings.rate_limit.enabled:
        raise RuntimeError("Configure redis for native Papilio rate limits")
    return providers


def task_providers(settings: PapilioSettings) -> list[Provider]:
    return [
        CoreProvider(settings),
        *infrastructure_providers(settings),
        *Bootstrapper(settings.app.modules).boot_providers(),
    ]
