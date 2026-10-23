"""Pure monetary validation, credit bounds and journal observations."""

from papilio_panel.shared.errors import InvalidInput
from papilio_panel.shared.money import MAX_MONEY_MINOR, Currency

from ..domain import (
    BalanceChange,
    BalanceObservation,
    EntryKind,
    JournalInput,
    WalletOpen,
    WalletRead,
)


def opening(values: WalletOpen) -> None:
    if values.currency != Currency.IRR:
        raise InvalidInput("This release supports IRR wallets with amounts in rials.")
    credit_limit(values.credit_limit_minor)


def credit_limit(amount_minor: int) -> None:
    if type(amount_minor) is not int or not 0 <= amount_minor <= MAX_MONEY_MINOR:
        raise InvalidInput("Choose a nonnegative credit limit within signed BIGINT.")


def entry(values: JournalInput) -> None:
    if type(values.amount_minor) is not int or not 1 <= values.amount_minor <= MAX_MONEY_MINOR:
        raise InvalidInput("Enter a positive integer amount within signed BIGINT.")
    if values.kind not in (EntryKind.CREDIT, EntryKind.DEBIT):
        raise InvalidInput("Choose credit or debit.")
    if (
        not values.reason.strip()
        or values.reason != values.reason.strip()
        or len(values.reason) > 500
    ):
        raise InvalidInput("Enter a reason up to 500 characters without surrounding whitespace.")


def balance_change(wallet: WalletRead, values: JournalInput) -> BalanceChange:
    if values.kind == EntryKind.CREDIT:
        result = BalanceChange(
            wallet.id,
            wallet.customer_id,
            wallet.revision,
            values.amount_minor,
            -wallet.credit_limit_minor,
            MAX_MONEY_MINOR - values.amount_minor,
        )
    else:
        result = BalanceChange(
            wallet.id,
            wallet.customer_id,
            wallet.revision,
            -values.amount_minor,
            values.amount_minor - wallet.credit_limit_minor,
            MAX_MONEY_MINOR,
        )
    return result


def observed_balance(after_minor: int, change: BalanceChange) -> BalanceObservation:
    return BalanceObservation(after_minor - change.delta_minor, after_minor)
