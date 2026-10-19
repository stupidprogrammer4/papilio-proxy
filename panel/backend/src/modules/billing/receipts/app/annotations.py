import asyncio
from collections.abc import Sequence

from papilio.errors.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import decrypt, encrypt

from src.config.pagination import ServicePage, page_size
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.domain.results import Principal
from src.modules.billing.receipts.app.annotation_interfaces import (
    IReceiptAnnotationCommand,
)
from src.modules.billing.receipts.domain.annotations import (
    ReceiptAnnotation,
    ReceiptAnnotationWrite,
    ReceiptCorrectionFields,
)
from src.modules.billing.receipts.domain.models import (
    PaymentReceiptAnnotationModel,
)
from src.modules.billing.receipts.infra.mysql import (
    PaymentReceiptAnnotationRepository,
    PaymentReceiptRepository,
)


class ReceiptAnnotationCommand(IReceiptAnnotationCommand):
    def __init__(
        self,
        receipts: PaymentReceiptRepository,
        annotations: PaymentReceiptAnnotationRepository,
        settings: PapilioSettings,
    ) -> None:
        self.receipts = receipts
        self.annotations = annotations
        self.settings = settings

    async def history(
        self,
        topup_id: int,
        receipt_id: int,
        principal: Principal,
        page: int,
        per_page: int | None,
    ) -> ServicePage[ReceiptAnnotation]:
        require_payment_scope(principal, "read")
        target = await self.receipts.annotation_target(topup_id, receipt_id)
        if target is None:
            raise receipt_missing(topup_id)
        limit = page_size(self.settings, per_page)
        result = await self.annotations.history(
            receipt_id, (page - 1) * limit, limit
        )
        items = await asyncio.to_thread(
            annotation_details,
            result.items,
            self.settings.configuration_encryption_key,
        )
        return ServicePage(items, result.total_items, limit)

    @handle_conflicts
    @transactional
    async def append(
        self,
        topup_id: int,
        receipt_id: int,
        principal: Principal,
        data: ReceiptAnnotationWrite,
    ) -> ReceiptAnnotation:
        require_payment_scope(principal, "update")
        target = await self.receipts.annotation_target(topup_id, receipt_id)
        if target is None:
            raise receipt_missing(topup_id)
        if target.annotation_revision != data.expected_revision:
            raise annotation_conflict(receipt_id)
        revision = data.expected_revision + 1
        encrypted_fields, encrypted_reason = await asyncio.to_thread(
            encrypt_annotation,
            data,
            self.settings.configuration_encryption_key,
        )
        advanced = await self.receipts.advance_annotation_revision(
            receipt_id, data.expected_revision
        )
        if not advanced:
            raise annotation_conflict(receipt_id)
        row = await self.annotations.create(
            PaymentReceiptAnnotationModel(
                receipt_id=receipt_id,
                revision=revision,
                staff_id=principal.staff_id,
                encrypted_fields=encrypted_fields,
                encrypted_reason=encrypted_reason,
            )
        )
        annotation = await asyncio.to_thread(
            annotation_detail, row, self.settings.configuration_encryption_key
        )
        return annotation


def encrypt_annotation(
    data: ReceiptAnnotationWrite, encryption_key: str
) -> tuple[str, str]:
    fields_ciphertext = encrypt(data.fields.model_dump_json(), encryption_key)
    reason_ciphertext = encrypt(data.reason, encryption_key)
    return fields_ciphertext, reason_ciphertext


def annotation_details(
    rows: Sequence[PaymentReceiptAnnotationModel], encryption_key: str
) -> list[ReceiptAnnotation]:
    return [annotation_detail(row, encryption_key) for row in rows]


def annotation_detail(
    row: PaymentReceiptAnnotationModel, encryption_key: str
) -> ReceiptAnnotation:
    if row.created_at is None:
        raise RuntimeError("Persisted annotation has no creation timestamp")
    return ReceiptAnnotation(
        id=row.id,
        receipt_id=row.receipt_id,
        revision=row.revision,
        staff_id=row.staff_id,
        created_at=row.created_at,
        fields=decrypt_fields(row.encrypted_fields, encryption_key),
        reason=decrypt(row.encrypted_reason, encryption_key),
    )


def decrypt_fields(
    ciphertext: str, encryption_key: str
) -> ReceiptCorrectionFields:
    return ReceiptCorrectionFields.model_validate_json(
        decrypt(ciphertext, encryption_key)
    )


def receipt_missing(topup_id: int) -> NotFoundException:
    return NotFoundException(
        message="پرداخت یا رسید پیدا نشد.",
        message_code="payment_receipt_not_found",
        entity="topup",
        identifier="id",
        identifier_value=topup_id,
    )


def annotation_conflict(receipt_id: int) -> ConflictException:
    return ConflictException(
        message="این رسید تغییر کرده است. نسخهٔ فعلی را بارگیری کنید.",
        message_code="receipt_annotation_revision_conflict",
        unique_dict={"receipt_id": receipt_id},
    )


def require_payment_scope(principal: Principal, level: str) -> None:
    allowed_scopes = {"*", "payments:*", f"payments:{level}"}
    if principal.scopes & allowed_scopes:
        return
    raise ForbiddenException(
        message="دسترسی به این بخش مجاز نیست.",
        message_code="admin_scope_denied",
    )
