from collections.abc import Awaitable
from typing import Protocol

from src.config.pagination import ServicePage
from src.modules.billing.destinations.domain.results import DestinationDetails
from src.modules.billing.sms_origins.domain.contracts import (
    DestinationBindingWrite,
    GeneratedParserSample,
    ManualSmsApproval,
    ParserPreviewRead,
    ParserProfileCreate,
    ParserProfileRead,
    ParserProfileUpdate,
    ParserRevisionRead,
    ReceivingRealmCreate,
    ReceivingRealmRead,
    ReceivingRealmUpdate,
    SmsOriginCapabilities,
    SmsOriginSearch,
    SmsSettlementCandidateRead,
    SmsSettlementReviewRead,
)
from src.modules.billing.sms_origins.domain.facts import SmsIntakeFacts
from src.modules.billing.sms_origins.domain.models import (
    ReceivingAliasModel,
    ReceivingRealmModel,
    SmsParserProfileModel,
    SmsParserRevisionModel,
    SmsSettlementClaimModel,
    SmsSettlementDecisionModel,
    SmsSettlementModel,
)


class ISmsOriginCapabilityQuery(Protocol):
    def get(self) -> SmsOriginCapabilities: ...


class ISmsParserProfileService(Protocol):
    def get(self, id: int) -> Awaitable[SmsParserProfileModel]: ...
    def locked(self, id: int) -> Awaitable[SmsParserProfileModel]: ...
    def create(
        self, title: str, is_active: bool
    ) -> Awaitable[SmsParserProfileModel]: ...
    def update(
        self, row: SmsParserProfileModel, title: str, is_active: bool
    ) -> Awaitable[SmsParserProfileModel]: ...
    def search(
        self, data: SmsOriginSearch
    ) -> Awaitable[ServicePage[SmsParserProfileModel]]: ...


class ISmsParserRevisionService(Protocol):
    def get(
        self, profile_id: int, revision: int
    ) -> Awaitable[SmsParserRevisionModel]: ...
    def create(
        self, row: SmsParserRevisionModel
    ) -> Awaitable[SmsParserRevisionModel]: ...
    def history(
        self, profile_id: int, data: SmsOriginSearch
    ) -> Awaitable[ServicePage[SmsParserRevisionModel]]: ...


class IReceivingRealmService(Protocol):
    def get(self, id: int) -> Awaitable[ReceivingRealmModel]: ...
    def locked(self, id: int) -> Awaitable[ReceivingRealmModel]: ...
    def create(
        self, title: str, active: bool, origin_enabled: bool
    ) -> Awaitable[ReceivingRealmModel]: ...
    def update(
        self,
        row: ReceivingRealmModel,
        title: str,
        active: bool,
        origin_enabled: bool,
    ) -> Awaitable[ReceivingRealmModel]: ...
    def search(
        self, data: SmsOriginSearch
    ) -> Awaitable[ServicePage[ReceivingRealmModel]]: ...


class ISmsParserCommand(Protocol):
    def create(
        self, data: ParserProfileCreate, staff_id: int
    ) -> Awaitable[ParserProfileRead]: ...
    def update(
        self, id: int, data: ParserProfileUpdate, staff_id: int
    ) -> Awaitable[ParserProfileRead]: ...
    def sample(
        self,
        profile_id: int,
        revision_number: int,
        data: GeneratedParserSample,
    ) -> Awaitable[ParserPreviewRead]: ...


class IReceivingRealmCommand(Protocol):
    def create(
        self, data: ReceivingRealmCreate
    ) -> Awaitable[ReceivingRealmRead]: ...
    def update(
        self, id: int, data: ReceivingRealmUpdate
    ) -> Awaitable[ReceivingRealmRead]: ...


class ISmsOriginAdmissionService(Protocol):
    def acquire(self) -> Awaitable[None]: ...
    def settlement_guard(self) -> Awaitable[None]: ...


class ISmsOriginQuery(Protocol):
    def profile(self, id: int) -> Awaitable[ParserProfileRead]: ...
    def profiles_page(
        self, data: SmsOriginSearch
    ) -> Awaitable[ServicePage[ParserProfileRead]]: ...
    def revision(
        self, id: int, revision: int
    ) -> Awaitable[ParserRevisionRead]: ...
    def revisions_page(
        self, id: int, data: SmsOriginSearch
    ) -> Awaitable[ServicePage[ParserRevisionRead]]: ...
    def realm(self, id: int) -> Awaitable[ReceivingRealmRead]: ...
    def realms_page(
        self, data: SmsOriginSearch
    ) -> Awaitable[ServicePage[ReceivingRealmRead]]: ...


class IReceivingAliasService(Protocol):
    def get(self, id: int) -> Awaitable[ReceivingAliasModel]: ...
    def resolve(
        self, realm_id: int, kind: str, digest: str, namespace: str | None
    ) -> Awaitable[ReceivingAliasModel]: ...
    def search(
        self, realm_id: int, data: SmsOriginSearch
    ) -> Awaitable[ServicePage[ReceivingAliasModel]]: ...


class IReceivingBindingCommand(Protocol):
    def assign(
        self, id: int, data: DestinationBindingWrite
    ) -> Awaitable[DestinationDetails]: ...


class ISmsOriginIntakeQuery(Protocol):
    def get(self, device_id: int) -> Awaitable[SmsIntakeFacts | None]: ...


class ISmsSettlementService(Protocol):
    def by_event(
        self, event_id: int
    ) -> Awaitable[SmsSettlementModel | None]: ...
    def create(
        self, data: SmsSettlementModel
    ) -> Awaitable[SmsSettlementModel]: ...


class ISmsSettlementClaimService(Protocol):
    def current_many(
        self, keys: list[tuple[str, str]]
    ) -> Awaitable[list[SmsSettlementClaimModel]]: ...
    def create_many(
        self, settlement_id: int, keys: list[tuple[str, str]]
    ) -> Awaitable[None]: ...


class ISmsSettlementDecisionService(Protocol):
    def get(
        self, event_id: int
    ) -> Awaitable[SmsSettlementDecisionModel | None]: ...
    def record(
        self, data: SmsSettlementDecisionModel
    ) -> Awaitable[SmsSettlementDecisionModel]: ...


class ISmsManualPaymentGuard(Protocol):
    def acquire_topup_creation(self) -> Awaitable[None]: ...
    def acquire(self, topup_id: int) -> Awaitable[None]: ...


class ISmsOriginSettlementCommand(Protocol):
    def check_event(
        self,
        event_id: str,
        *,
        expected_topup_id: int | None = None,
        manual: ManualSmsApproval | None = None,
        staff_id: int | None = None,
    ) -> Awaitable[str]: ...


class ISmsSettlementReviewQuery(Protocol):
    def get(self, id: int) -> Awaitable[SmsSettlementReviewRead]: ...


class ISmsSettlementCandidateQuery(Protocol):
    def get(
        self, id: int, data: SmsOriginSearch
    ) -> Awaitable[ServicePage[SmsSettlementCandidateRead]]: ...


class ISmsApprovedFundingQuery(Protocol):
    def get(self, event_id: int) -> Awaitable[int | None]: ...
