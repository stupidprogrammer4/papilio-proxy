"""Explicit wallet/journal read models with authoritative customer scopes."""

from uuid import UUID

from django.core.paginator import EmptyPage, Paginator

from papilio_panel.shared.errors import Missing
from papilio_panel.shared.money import Currency

from ..domain import EntryKind, JournalEntryRead, JournalPage, JournalSearch, WalletRead
from ..models import JournalEntry, Wallet


def wallet_read(row: Wallet) -> WalletRead:
    return WalletRead(
        row.id,
        row.customer_id,
        Currency(row.currency),
        row.balance_minor,
        row.credit_limit_minor,
        row.revision,
    )


def entry_read(row: JournalEntry) -> JournalEntryRead:
    if row.balance_before_minor is None or row.balance_after_minor is None:
        raise RuntimeError("A journal reservation was not finalized in its transaction.")
    return JournalEntryRead(
        row.id,
        row.wallet_id,
        row.request_key,
        EntryKind(row.kind),
        row.amount_minor,
        row.reason,
        row.balance_before_minor,
        row.balance_after_minor,
        row.created_at,
        Currency(row.wallet.currency),
        row.actor_id,
    )


class DjangoWalletReader:
    def read(self, customer_id: UUID, actor_id: int) -> WalletRead:
        try:
            row = Wallet.objects.get(customer_id=customer_id, customer__owner_id=actor_id)
        except Wallet.DoesNotExist as error:
            raise Missing("The customer wallet was not found.") from error
        return wallet_read(row)

    def read_entry(self, entry_id: UUID, customer_id: UUID, actor_id: int) -> JournalEntryRead:
        try:
            row = JournalEntry.objects.select_related("wallet").get(
                pk=entry_id, wallet__customer_id=customer_id, wallet__customer__owner_id=actor_id
            )
        except JournalEntry.DoesNotExist as error:
            raise Missing("The wallet journal entry was not found.") from error
        return entry_read(row)

    def search(self, values: JournalSearch) -> JournalPage:
        rows = (
            JournalEntry.objects.filter(
                wallet__customer_id=values.customer_id, wallet__customer__owner_id=values.actor_id
            )
            .select_related("wallet")
            .order_by("created_at", "id")
        )
        if values.query:
            rows = rows.filter(reason__icontains=values.query)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The wallet journal page was not found.") from error
        return JournalPage(
            tuple(entry_read(row) for row in page), paginator.count, values.page, values.page_size
        )
