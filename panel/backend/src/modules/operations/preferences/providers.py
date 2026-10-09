from dishka import Provider, Scope, provide

from src.modules.operations.preferences.app.services import PreferencesService
from src.modules.operations.preferences.infra.mysql import (
    PreferencesRepository,
)
from src.modules.operations.preferences.interfaces import IPreferencesService


class PreferencesProvider(Provider):
    scope = Scope.REQUEST
    repo = provide(PreferencesRepository)
    service = provide(PreferencesService, provides=IPreferencesService)
