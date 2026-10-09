from papilio.infra.db.table import BaseTable
from sqlalchemy import Index

from src.modules.billing.wallet.domain.models import (
    TopupModel,
    WalletEntryModel,
    WalletModel,
)


class WalletTable(WalletModel, BaseTable, table=True):
    pass


class WalletEntryTable(WalletEntryModel, BaseTable, table=True):
    __table_args__ = (Index("ix_wallet_entry_wallet_id", "wallet_id", "id"),)


class TopupTable(TopupModel, BaseTable, table=True):
    __table_args__ = (
        Index("ix_topup_realm_amount", "receiving_realm_id", "amount_rial"),
        Index(
            "ix_topup_realm_status_amount",
            "receiving_realm_id",
            "status",
            "amount_rial",
        ),
        Index("ix_topup_status_id", "status", "id"),
        Index("ix_topup_amount_status_id", "amount_rial", "status", "id"),
    )
