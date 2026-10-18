from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.billing.sms_origins.domain.contracts import SmsSettlementProof
from src.modules.billing.wallet.domain.dtos import (
    TopupApproval,
    TopupCreate,
    TopupRejection,
    TopupSearch,
    WalletLedgerSearch,
)
from src.modules.billing.wallet.domain.models import TopupModel
from src.modules.billing.wallet.domain.results import (
    TopupPaymentInstructionRead,
    WalletLedgerFacts,
)


class ITopupInstructionQuery(Protocol):
    def get(
        self, id: int, customer_id: int | None = None
    ) -> Awaitable[TopupPaymentInstructionRead | None]: ...


class ITopupRecordService(Protocol):
    def get(self, id: int) -> Awaitable[TopupModel | None]: ...
    def locked(self, id: int) -> Awaitable[TopupModel | None]: ...


class IWalletCommand(Protocol):
    def get_topup(self, id: int) -> Awaitable[TopupModel]: ...
    def request_topup(self, data: TopupCreate) -> Awaitable[TopupModel]: ...
    def approve(
        self, id: int, data: TopupApproval, staff_id: int
    ) -> Awaitable[TopupModel]: ...
    def approve_from_sms(
        self, id: int, sms_id: int, device_id: int, bank_reference: str
    ) -> Awaitable[TopupModel]: ...
    def approve_from_sms_proof(
        self, id: int, proof: SmsSettlementProof
    ) -> Awaitable[TopupModel]: ...
    def reject(
        self, id: int, data: TopupRejection, staff_id: int
    ) -> Awaitable[TopupModel]: ...
    def balance(self, customer_id: int) -> Awaitable[int]: ...
    def search(
        self, data: TopupSearch
    ) -> Awaitable[ServicePage[TopupModel]]: ...


class IWalletLedgerQuery(Protocol):
    def search(
        self, customer_id: int, data: WalletLedgerSearch
    ) -> Awaitable[ServicePage[WalletLedgerFacts]]: ...
