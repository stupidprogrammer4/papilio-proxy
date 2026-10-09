from dishka import Provider, Scope, provide

from src.modules.support.app.commands import (
    SupportCreateCommand,
    SupportThreadCommand,
)
from src.modules.support.app.queries import (
    SupportHistoryQuery,
    SupportMessageQuery,
    SupportPolicyQuery,
    SupportTicketQuery,
)
from src.modules.support.infra.mysql import (
    SupportMessageRepository,
    SupportStateChangeRepository,
    SupportTicketRepository,
)
from src.modules.support.infra.readers import SupportContextReader
from src.modules.support.interfaces import (
    ISupportCreateCommand,
    ISupportHistoryQuery,
    ISupportMessageQuery,
    ISupportPolicyQuery,
    ISupportThreadCommand,
    ISupportTicketQuery,
)


class SupportProvider(Provider):
    scope = Scope.REQUEST
    tickets = provide(SupportTicketRepository)
    messages = provide(SupportMessageRepository)
    changes = provide(SupportStateChangeRepository)
    contexts = provide(SupportContextReader)
    policy = provide(SupportPolicyQuery, provides=ISupportPolicyQuery)
    ticket_query = provide(SupportTicketQuery, provides=ISupportTicketQuery)
    message_query = provide(SupportMessageQuery, provides=ISupportMessageQuery)
    history_query = provide(SupportHistoryQuery, provides=ISupportHistoryQuery)
    create = provide(SupportCreateCommand, provides=ISupportCreateCommand)
    thread = provide(SupportThreadCommand, provides=ISupportThreadCommand)
