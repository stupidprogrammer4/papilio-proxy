"""Native entry uniqueness and conditional balance updates within caller transactions."""

from uuid import UUID

from django.db.models import F

from papilio_panel.shared.errors import Conflict

from ..domain import (
    BalanceChange,
    BalanceObservation,
    EntryKind,
    JournalInput,
    JournalReservation,
    WalletChange,
    WalletOpen,
    WalletOpening,
    WalletRead,
)
from ..models import JournalEntry, Wallet
from .readers import DjangoWalletReader, wallet_read


class DjangoWalletStorage(DjangoWalletReader):
    def open(self, values: WalletOpen) -> WalletOpening:
        row, created = Wallet.objects.get_or_create(
            customer_id=values.customer_id,
            defaults={"currency": values.currency, "credit_limit_minor": values.credit_limit_minor},
        )
        return WalletOpening(wallet_read(row), created)

    def change(
        self, wallet_id: UUID, values: WalletChange, minimum_balance_minor: int
    ) -> WalletRead:
        changed = Wallet.objects.filter(
            pk=wallet_id,
            customer_id=values.customer_id,
            revision=values.expected_revision,
            balance_minor__gte=minimum_balance_minor,
        ).update(credit_limit_minor=values.credit_limit_minor, revision=F("revision") + 1)
        if changed != 1:
            raise Conflict(
                "Wallet settings changed or the balance exceeds the requested credit limit."
            )
        return self.read(values.customer_id, values.actor_id)

    def reserve(self, wallet_id: UUID, actor_id: int, values: JournalInput) -> JournalReservation:
        row, created = JournalEntry.objects.get_or_create(
            wallet_id=wallet_id,
            request_key=values.request_key,
            defaults={
                "actor_id": actor_id,
                "kind": values.kind,
                "amount_minor": values.amount_minor,
                "reason": values.reason,
            },
        )
        original = JournalInput(row.request_key, EntryKind(row.kind), row.amount_minor, row.reason)
        return JournalReservation(row.id, original, created)

    def change_balance(self, change: BalanceChange, actor_id: int) -> int:
        changed = Wallet.objects.filter(
            pk=change.wallet_id,
            customer_id=change.customer_id,
            revision=change.expected_revision,
            balance_minor__gte=change.minimum_before_minor,
            balance_minor__lte=change.maximum_before_minor,
        ).update(balance_minor=F("balance_minor") + change.delta_minor)
        if changed != 1:
            raise Conflict("The wallet balance cannot accept this change within its limits.")
        row = Wallet.objects.get(pk=change.wallet_id, customer__owner_id=actor_id)
        return row.balance_minor

    def complete_entry(self, entry_id: UUID, observation: BalanceObservation) -> None:
        JournalEntry.objects.filter(pk=entry_id).update(
            balance_before_minor=observation.before_minor,
            balance_after_minor=observation.after_minor,
        )
