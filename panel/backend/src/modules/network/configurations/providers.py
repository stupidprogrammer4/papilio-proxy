from dishka import Provider, Scope, provide

from src.modules.network.configurations.app.commands import ProfileCommand
from src.modules.network.configurations.app.configurations import (
    ConfigurationCommand,
)
from src.modules.network.configurations.app.management_sockets import (
    OpenVpnSocketService,
)
from src.modules.network.configurations.app.queries import (
    SubscriptionFeedQuery,
)
from src.modules.network.configurations.infra.mysql import (
    ConfigurationJsonRevisionRepository,
    ConfigurationRepository,
    InboundPortRepository,
    OpenVpnSocketRepository,
    ProfileRepository,
    SubscriptionLinkRepository,
)
from src.modules.network.configurations.infra.readers import (
    ConfigurationFactsReader,
)
from src.modules.network.configurations.interfaces import (
    IConfigurationCommand,
    IOpenVpnSocketService,
    IProfileCommand,
    ISubscriptionFeedQuery,
)


class ConfigurationProvider(Provider):
    scope = Scope.REQUEST
    configurations = provide(ConfigurationRepository)
    json_revisions = provide(ConfigurationJsonRevisionRepository)
    ports = provide(InboundPortRepository)
    sockets = provide(OpenVpnSocketRepository)
    socket_service = provide(
        OpenVpnSocketService, provides=IOpenVpnSocketService
    )
    profiles = provide(ProfileRepository)
    links = provide(SubscriptionLinkRepository)
    facts = provide(ConfigurationFactsReader)
    service = provide(ConfigurationCommand, provides=IConfigurationCommand)
    command = provide(ProfileCommand, provides=IProfileCommand)
    feed = provide(SubscriptionFeedQuery, provides=ISubscriptionFeedQuery)
