from dishka import Provider, Scope, provide

from src.modules.sales.trials.app.commands import TrialCommand
from src.modules.sales.trials.app.queries import TrialPolicyQuery, TrialQuery
from src.modules.sales.trials.infra.readers import TrialUsageReader
from src.modules.sales.trials.interfaces import (
    ITrialCommand,
    ITrialPolicyQuery,
    ITrialQuery,
)


class TrialProvider(Provider):
    scope = Scope.REQUEST
    usage = provide(TrialUsageReader)
    policy = provide(TrialPolicyQuery, provides=ITrialPolicyQuery)
    query = provide(TrialQuery, provides=ITrialQuery)
    command = provide(TrialCommand, provides=ITrialCommand)
