from dishka import Provider, Scope, provide

from src.modules.billing.wallet.app.commands import WalletCommand
from src.modules.billing.wallet.app.instructions import TopupInstructionQuery
from src.modules.billing.wallet.app.queries import WalletLedgerQuery
from src.modules.billing.wallet.infra.mysql import (
    TopupRepository,
    WalletRepository,
)
from src.modules.billing.wallet.infra.readers import WalletLedgerReader
from src.modules.billing.wallet.interfaces import (
    ITopupInstructionQuery,
    IWalletCommand,
    IWalletLedgerQuery,
)


class WalletProvider(Provider):
    scope = Scope.REQUEST
    instruction = provide(
        TopupInstructionQuery, provides=ITopupInstructionQuery
    )
    wallets = provide(WalletRepository)
    topups = provide(TopupRepository)
    command = provide(WalletCommand, provides=IWalletCommand)
    ledger_reader = provide(WalletLedgerReader)
    ledger_query = provide(WalletLedgerQuery, provides=IWalletLedgerQuery)
