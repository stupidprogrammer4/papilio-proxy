from src.modules.billing.wallet.domain.models import (
    WalletEntryModel,
    WalletModel,
)


def ledger_entry(
    wallet: WalletModel, amount_rial: int, reference: str, reason: str
) -> WalletEntryModel:
    balance = wallet.balance_rial + amount_rial
    if balance < 0:
        raise ValueError("Wallet balance cannot become negative")
    return WalletEntryModel(
        wallet_id=wallet.id,
        amount_rial=amount_rial,
        balance_after_rial=balance,
        reference=reference,
        reason=reason,
    )
