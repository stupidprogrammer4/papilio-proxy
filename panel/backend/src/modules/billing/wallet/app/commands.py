import asyncio

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import encrypt

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)
from src.modules.billing.payment_identifiers.app.allocation import (
    allocation_conflict,
)
from src.modules.billing.payment_identifiers.domain.contracts import (
    PERSISTED_RIAL_MAXIMUM,
    RIAL_SUFFIX_MODULUS,
    PaymentAmountAllocation,
)
from src.modules.billing.payment_identifiers.domain.models import (
    PaymentAmountReservationModel,
)
from src.modules.billing.payment_identifiers.interfaces import (
    IPaymentAmountAllocationQuery,
    IPaymentAmountReservationService,
)
from src.modules.billing.sms_origins.domain.contracts import SmsSettlementProof
from src.modules.billing.sms_origins.interfaces import (
    IReceivingAliasService,
    IReceivingRealmService,
    ISmsManualPaymentGuard,
)
from src.modules.billing.wallet.app.ledger import ledger_entry
from src.modules.billing.wallet.domain.dtos import (
    TopupApproval,
    TopupCreate,
    TopupRejection,
    TopupSearch,
)
from src.modules.billing.wallet.domain.models import TopupModel, WalletModel
from src.modules.billing.wallet.infra.mysql import (
    TopupRepository,
    WalletRepository,
)
from src.modules.operations.notifications.domain.dtos import (
    NotificationEvent,
    NotificationKind,
)
from src.modules.operations.notifications.interfaces import (
    INotificationCreateCommand,
)
from src.modules.operations.preferences.interfaces import IPreferencesService


class WalletCommand:
    def __init__(
        self,
        customers: CustomerRepository,
        wallets: WalletRepository,
        topups: TopupRepository,
        settings: PapilioSettings,
        preferences: IPreferencesService,
        destinations: IPaymentDestinationService,
        notifications: INotificationCreateCommand,
        sms_guard: ISmsManualPaymentGuard,
        receiving_aliases: IReceivingAliasService,
        receiving_realms: IReceivingRealmService,
        payment_amounts: IPaymentAmountAllocationQuery,
        payment_reservations: IPaymentAmountReservationService,
    ) -> None:
        self.customers = customers
        self.wallets = wallets
        self.topups = topups
        self.settings = settings
        self.preferences = preferences
        self.destinations = destinations
        self.notifications = notifications
        self.sms_guard = sms_guard
        self.receiving_aliases = receiving_aliases
        self.receiving_realms = receiving_realms
        self.payment_amounts = payment_amounts
        self.payment_reservations = payment_reservations

    async def get_topup(self, id: int) -> TopupModel:
        result = await self.topups.get_by_id(id)
        if result is None:
            raise _missing(id)
        return result

    async def locked_topup_after_customer(
        self, id: int, *, guard: bool = False
    ) -> TopupModel:
        owner_id = await self.topups.owner_id(id)
        if owner_id is None:
            raise _missing(id)
        customer = await self.customers.locked(owner_id)
        if customer is None:
            raise _missing(id)
        if guard:
            await self.sms_guard.acquire(id)
        topup = await self.topups.locked(id)
        if topup is None or topup.customer_id != customer.id:
            raise _missing(id)
        return topup

    @handle_conflicts
    @transactional
    async def request_topup(self, data: TopupCreate) -> TopupModel:
        customer = await self.customers.locked(data.customer_id)
        if customer is None:
            raise NotFoundException(
                message="مشتری فعال پیدا نشد.",
                message_code="customer_not_found",
                entity="customer",
                identifier="id",
                identifier_value=data.customer_id,
            )
        await self.sms_guard.acquire_topup_creation()
        if data.request_key is not None:
            existing = await self.topups.by_request_key(data.request_key)
            if existing is not None:
                original_amount = existing.requested_amount_rial
                if original_amount is None:
                    original_amount = existing.amount_rial
                if (
                    existing.customer_id != data.customer_id
                    or original_amount != data.amount_rial
                    or existing.destination_id != data.destination_id
                ):
                    raise ConflictException(
                        message=(
                            "کلید درخواست برای پرداخت دیگری استفاده شده است."
                        ),
                        message_code="topup_request_reused",
                        unique_dict={"id": existing.id},
                    )
                return existing
        if not customer.is_active:
            raise NotFoundException(
                message="مشتری فعال پیدا نشد.",
                message_code="customer_not_found",
                entity="customer",
                identifier="id",
                identifier_value=data.customer_id,
            )
        policy = (
            await self.preferences.current()
        ).values.checkout or self.settings.checkout.policy
        if (
            not policy.minimum_topup_rial
            <= data.amount_rial
            <= min(
                policy.maximum_topup_rial,
                self.settings.checkout.maximum_topup_rial,
                PERSISTED_RIAL_MAXIMUM,
            )
        ):
            raise ConflictException(
                message="مبلغ شارژ خارج از بازهٔ مجاز است.",
                message_code="topup_amount_policy",
                unique_dict={"customer_id": data.customer_id},
            )
        if (
            policy.destination_mode == "required"
            and data.destination_id is None
        ):
            raise ConflictException(
                message="انتخاب مقصد پرداخت لازم است.",
                message_code="payment_destination_required",
                unique_dict={"customer_id": data.customer_id},
            )
        hint = (
            await self.destinations.instruction_details(data.destination_id)
            if data.destination_id is not None
            else None
        )
        alias = (
            await self.receiving_aliases.get(hint.receiving_alias_id)
            if hint is not None and hint.receiving_alias_id is not None
            else None
        )
        realm = (
            await self.receiving_realms.locked(alias.realm_id)
            if alias is not None
            else None
        )
        instruction = (
            await self.destinations.locked(data.destination_id)
            if data.destination_id is not None
            else None
        )
        if instruction is not None and hint is not None:
            if (
                instruction.revision != hint.revision
                or instruction.receiving_alias_id != hint.receiving_alias_id
                or not instruction.is_active
                or instruction.kind not in policy.allowed_methods
                or policy.destination_mode == "legacy"
            ):
                raise allocation_conflict("payment_identifier_binding_changed")
        allocation = PaymentAmountAllocation(
            data.amount_rial, data.amount_rial, "exact_requested", None
        )
        identifier_policy = policy.payment_identifier
        if (
            identifier_policy is not None
            and identifier_policy.mode == "rial_suffix4"
        ):
            if realm is None or alias is None or not realm.is_active:
                raise allocation_conflict(
                    "payment_identifier_receiving_realm_required"
                )
            allocation = await self.payment_amounts.allocate(
                data.amount_rial,
                realm.id,
                identifier_policy,
                policy.maximum_topup_rial,
            )
        encrypted_instruction = None
        if instruction is not None:
            instruction_json = instruction.model_dump_json()
            encrypted_instruction = await asyncio.to_thread(
                encrypt,
                instruction_json,
                self.settings.configuration_encryption_key,
            )
        result = await self.topups.create(
            TopupModel(
                request_key=data.request_key,
                destination_id=data.destination_id,
                customer_id=data.customer_id,
                amount_rial=allocation.payable_amount_rial,
                requested_amount_rial=allocation.requested_amount_rial,
                payment_identifier_mode=allocation.mode,
                payment_identifier_code4=allocation.code4,
                receiving_realm_id=alias.realm_id
                if alias is not None
                else None,
                receiving_alias_id=alias.id if alias is not None else None,
                captured_destination_revision=instruction.revision
                if instruction is not None
                else None,
                encrypted_instruction=encrypted_instruction,
                status="pending",
            )
        )
        if allocation.reserve_amount:
            assert realm is not None
            suffix = allocation.payable_amount_rial % RIAL_SUFFIX_MODULUS
            await self.payment_reservations.create(
                PaymentAmountReservationModel(
                    receiving_realm_id=realm.id,
                    topup_id=result.id,
                    requested_amount_rial=allocation.requested_amount_rial,
                    payable_amount_rial=allocation.payable_amount_rial,
                    code4=f"{suffix:04d}",
                )
            )
        return result

    @handle_conflicts
    @transactional
    async def approve(
        self, id: int, data: TopupApproval, staff_id: int
    ) -> TopupModel:
        topup = await self.locked_topup_after_customer(id, guard=True)
        if (
            topup.status == "approved"
            and topup.bank_reference == data.bank_reference
        ):
            return topup
        if topup.revision != data.expected_revision:
            raise revision_conflict(id)
        if topup.status != "pending":
            raise ConflictException(
                message="این درخواست قبلاً بررسی شده است.",
                message_code="topup_reviewed",
                unique_dict={"topup_id": id},
            )
        wallet = await self.wallets.locked_for_customer(
            WalletModel(customer_id=topup.customer_id, balance_rial=0)
        )
        await self.wallets.record(
            wallet,
            ledger_entry(
                wallet,
                topup.amount_rial,
                f"topup:{topup.id}",
                "approved_topup",
            ),
        )
        result = await self.topups.update_existing(
            topup,
            TopupModel.patch(
                status="approved",
                revision=topup.revision + 1,
                bank_reference=data.bank_reference,
                approved_by_staff_id=staff_id,
            ),
        )
        await self.notifications.enqueue(
            topup.customer_id,
            NotificationEvent(
                event_key=f"payment:{id}:approved",
                kind=NotificationKind.PAYMENT_APPROVED,
                status="تأییدشده",
                record_id=id,
                amount_rial=topup.amount_rial,
            ),
        )
        return result

    @handle_conflicts
    @transactional
    async def approve_from_sms(
        self, id: int, sms_id: int, device_id: int, bank_reference: str
    ) -> TopupModel:
        topup = await self.locked_topup_after_customer(id)
        if topup.status == "approved" and topup.approved_by_sms_id == sms_id:
            return topup
        if topup.status != "pending":
            raise ConflictException(
                message="Payment has already been reviewed",
                message_code="topup_reviewed",
                unique_dict={"topup_id": id},
            )
        wallet = await self.wallets.locked_for_customer(
            WalletModel(customer_id=topup.customer_id, balance_rial=0)
        )
        await self.wallets.record(
            wallet,
            ledger_entry(
                wallet, topup.amount_rial, f"topup:{id}", "approved_topup"
            ),
        )
        result = await self.topups.update_existing(
            topup,
            TopupModel.patch(
                status="approved",
                revision=topup.revision + 1,
                bank_reference=bank_reference,
                approved_by_staff_id=None,
                approved_by_device_id=device_id,
                approved_by_sms_id=sms_id,
            ),
        )
        await self.notifications.enqueue(
            topup.customer_id,
            NotificationEvent(
                event_key=f"payment:{id}:approved",
                kind=NotificationKind.PAYMENT_APPROVED,
                status="SMS confirmed",
                record_id=id,
                amount_rial=topup.amount_rial,
            ),
        )
        return result

    @handle_conflicts
    @transactional
    async def approve_from_sms_proof(
        self, id: int, proof: SmsSettlementProof
    ) -> TopupModel:
        topup = await self.locked_topup_after_customer(id, guard=True)
        sms_id, device_id = proof.sms_event_id, proof.device_id
        bank_reference = proof.actual_bank_reference
        if topup.amount_rial != proof.observed_amount_rial:
            raise ConflictException(
                message="Observed amount does not match.",
                message_code="sms_topup_amount_changed",
                unique_dict={},
            )
        if bank_reference is None and (
            proof.evidence_kind != "trusted_sms_origin"
            or proof.origin_identity_sha256 is None
            or proof.declared_notification_sha256 is None
        ):
            raise ConflictException(
                message="Settlement identity required.",
                message_code="sms_settlement_identity_required",
                unique_dict={},
            )
        if topup.status == "approved" and topup.approved_by_sms_id == sms_id:
            return topup
        if topup.status != "pending":
            raise ConflictException(
                message="Payment has already been reviewed",
                message_code="topup_reviewed",
                unique_dict={"topup_id": id},
            )
        wallet = await self.wallets.locked_for_customer(
            WalletModel(customer_id=topup.customer_id, balance_rial=0)
        )
        await self.wallets.record(
            wallet,
            ledger_entry(
                wallet, topup.amount_rial, f"topup:{id}", "approved_topup"
            ),
        )
        result = await self.topups.update_existing(
            topup,
            TopupModel.patch(
                status="approved",
                revision=topup.revision + 1,
                bank_reference=bank_reference,
                approved_by_staff_id=None,
                approved_by_device_id=device_id,
                approved_by_sms_id=sms_id,
            ),
        )
        await self.notifications.enqueue(
            topup.customer_id,
            NotificationEvent(
                event_key=f"payment:{id}:approved",
                kind=NotificationKind.PAYMENT_APPROVED,
                status="SMS confirmed",
                record_id=id,
                amount_rial=topup.amount_rial,
            ),
        )
        return result

    @transactional
    async def reject(
        self, id: int, data: TopupRejection, staff_id: int
    ) -> TopupModel:
        topup = await self.topups.locked(id)
        if topup is None:
            raise _missing(id)
        if topup.revision != data.expected_revision:
            raise revision_conflict(id)
        if topup.status != "pending":
            raise ConflictException(
                message="این درخواست قبلاً بررسی شده است.",
                message_code="topup_reviewed",
                unique_dict={"topup_id": id},
            )
        result = await self.topups.update_existing(
            topup,
            TopupModel.patch(
                status="rejected",
                revision=topup.revision + 1,
                approved_by_staff_id=staff_id,
            ),
        )
        return result

    async def balance(self, customer_id: int) -> int:
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundException(
                message="مشتری پیدا نشد.",
                message_code="customer_not_found",
                entity="customer",
                identifier="id",
                identifier_value=customer_id,
            )
        wallet = await self.wallets.by_customer(customer_id)
        return 0 if wallet is None else wallet.balance_rial

    async def search(self, data: TopupSearch) -> ServicePage[TopupModel]:
        limit = page_size(self.settings, data.per_page)
        result = await self.topups.page(
            data.status,
            data.customer_id,
            (data.page - 1) * limit,
            limit,
        )
        return service_page(result, limit)


def _missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="درخواست شارژ پیدا نشد.",
        message_code="topup_not_found",
        entity="topup",
        identifier="id",
        identifier_value=id,
    )


def revision_conflict(id: int) -> ConflictException:
    return ConflictException(
        message=(
            "این درخواست شارژ تغییر کرده است. نسخهٔ فعلی را بارگیری کنید."
        ),
        message_code="topup_revision_conflict",
        unique_dict={"topup_id": id},
    )
