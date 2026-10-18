from dishka import Provider, Scope, provide

from src.modules.bot.app.commands import BotCommand
from src.modules.bot.app.interfaces import IBotPresentationQuery
from src.modules.bot.app.queries.presentation import BotPresentationQuery
from src.modules.bot.app.trials import BotTrialCommand
from src.modules.bot.interfaces import IBotCommand, IBotTrialCommand


class BotProvider(Provider):
    scope = Scope.REQUEST
    trials = provide(BotTrialCommand, provides=IBotTrialCommand)
    command = provide(BotCommand, provides=IBotCommand)
    presentation = provide(
        BotPresentationQuery, provides=IBotPresentationQuery
    )
