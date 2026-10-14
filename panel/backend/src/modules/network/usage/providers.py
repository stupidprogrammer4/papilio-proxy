from dishka import Provider, Scope, alias, provide

from src.modules.network.usage.app.commands import UsageCommand
from src.modules.network.usage.app.events import UsageEventService
from src.modules.network.usage.app.grants import UsageGrantService
from src.modules.network.usage.app.queries import UsageQuery
from src.modules.network.usage.infra.mysql import (
    UsageEventRepository,
    UsageGrantRepository,
)
from src.modules.network.usage.infra.readers import UsageFactsReader
from src.modules.network.usage.interfaces import (
    IUsageCommand,
    IUsageEventService,
    IUsageFactsReader,
    IUsageGrantService,
    IUsageQuery,
)


class UsageProvider(Provider):
    scope = Scope.REQUEST
    grants = provide(UsageGrantRepository)
    events = provide(UsageEventRepository)
    facts = provide(UsageFactsReader)
    facts_interface = alias(UsageFactsReader, provides=IUsageFactsReader)
    grant_service = provide(UsageGrantService, provides=IUsageGrantService)
    event_service = provide(UsageEventService, provides=IUsageEventService)
    command = provide(UsageCommand, provides=IUsageCommand)
    query = provide(UsageQuery, provides=IUsageQuery)
