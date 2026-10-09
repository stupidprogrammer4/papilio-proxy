from dishka import Provider, Scope, provide

from src.modules.network.usage.app.commands import UsageCommand
from src.modules.network.usage.app.queries import UsageQuery
from src.modules.network.usage.infra.mysql import (
    UsageEventRepository,
    UsageGrantRepository,
)
from src.modules.network.usage.infra.readers import UsageFactsReader
from src.modules.network.usage.interfaces import IUsageCommand, IUsageQuery


class UsageProvider(Provider):
    scope = Scope.REQUEST
    grants = provide(UsageGrantRepository)
    events = provide(UsageEventRepository)
    facts = provide(UsageFactsReader)
    command = provide(UsageCommand, provides=IUsageCommand)
    query = provide(UsageQuery, provides=IUsageQuery)
