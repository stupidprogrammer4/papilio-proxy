import asyncio
import base64
from hashlib import sha256

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import decrypt, encrypt

from src.config.pagination import ServicePage, page_size
from src.config.settings import PapilioSettings
from src.modules.billing.receipts.app.images import ReceiptImages
from src.modules.billing.receipts.domain.models import PaymentReceiptModel
from src.modules.billing.receipts.domain.results import (
    ReceiptDetails,
    ReceiptDownload,
)
from src.modules.billing.receipts.infra.mysql import PaymentReceiptRepository
from src.modules.billing.wallet.infra.mysql import TopupRepository
from src.modules.operations.preferences.interfaces import IPreferencesService


class PaymentReceiptCommand:
    def __init__(
        self,
        repo: PaymentReceiptRepository,
        topups: TopupRepository,
        settings: PapilioSettings,
        preferences: IPreferencesService,
        images: ReceiptImages,
    ) -> None:
        self.repo = repo
        self.topups = topups
        self.settings = settings
        self.preferences = preferences
        self.images = images

    @handle_conflicts
    @transactional
    async def upload(
        self, topup_id: int, customer_id: int | None, content: bytes
    ) -> ReceiptDetails:
        policy = (await self.preferences.current()).values.receipts
        assert policy is not None
        if (
            not policy.enabled
            or not self.settings.receipts.enabled
            or not content
            or len(content) > self.settings.receipts.max_image_bytes
        ):
            raise ConflictException(
                message=(
                    "ارسال رسید غیرفعال است یا حجم آن بیش از حد مجاز است."
                ),
                message_code="receipt_upload_unavailable",
                unique_dict={"topup_id": topup_id},
            )
        normalized = await self.images.process(content, policy)
        topup = await self.topups.locked(topup_id)
        if topup is None or (
            customer_id is not None and topup.customer_id != customer_id
        ):
            raise missing(topup_id)
        hasher = await asyncio.to_thread(sha256, normalized.content)
        digest = hasher.hexdigest()
        existing = await self.repo.by_content(topup_id, digest)
        if existing is not None:
            return ReceiptDetails.model_validate(
                existing, from_attributes=True
            )
        if topup.status != "pending":
            raise ConflictException(
                message="این پرداخت قبلاً بررسی شده است.",
                message_code="topup_reviewed",
                unique_dict={"topup_id": topup_id},
            )
        count = await self.repo.count(topup_id)
        if count >= policy.max_per_topup:
            raise ConflictException(
                message="تعداد رسیدهای این پرداخت به حد مجاز رسیده است.",
                message_code="receipt_capacity",
                unique_dict={"topup_id": topup_id},
            )
        encoded_bytes = await asyncio.to_thread(
            base64.b64encode, normalized.content
        )
        encoded_text = await asyncio.to_thread(
            bytes.decode, encoded_bytes, "ascii"
        )
        ciphertext = await asyncio.to_thread(
            encrypt, encoded_text, self.settings.configuration_encryption_key
        )
        result = await self.repo.create(
            PaymentReceiptModel(
                topup_id=topup_id,
                content_hash=digest,
                media_type=normalized.media_type,
                size_bytes=len(normalized.content),
                encrypted_payload=ciphertext,
            )
        )
        return ReceiptDetails.model_validate(result, from_attributes=True)

    async def search(
        self,
        topup_id: int,
        customer_id: int | None,
        page: int,
        per_page: int | None,
    ) -> ServicePage[ReceiptDetails]:
        await self._owned(topup_id, customer_id)
        limit = page_size(self.settings, per_page)
        result = await self.repo.page(topup_id, (page - 1) * limit, limit)
        return ServicePage(
            [
                ReceiptDetails.model_validate(row, from_attributes=True)
                for row in result.items
            ],
            result.total_items,
            limit,
        )

    async def download(
        self, topup_id: int, id: int, customer_id: int | None
    ) -> ReceiptDownload:
        await self._owned(topup_id, customer_id)
        row = await self.repo.get_by_id(id)
        if row is None or row.topup_id != topup_id:
            raise missing(topup_id)
        plaintext = await asyncio.to_thread(
            decrypt,
            row.encrypted_payload,
            self.settings.configuration_encryption_key,
        )
        content = await asyncio.to_thread(
            base64.b64decode, plaintext, validate=True
        )
        return ReceiptDownload(content=content, media_type=row.media_type)

    async def _owned(self, topup_id: int, customer_id: int | None) -> None:
        topup = await self.topups.get_by_id(topup_id)
        if topup is None or (
            customer_id is not None and topup.customer_id != customer_id
        ):
            raise missing(topup_id)


def missing(topup_id: int) -> NotFoundException:
    return NotFoundException(
        message="پرداخت یا رسید پیدا نشد.",
        message_code="payment_receipt_not_found",
        entity="topup",
        identifier="id",
        identifier_value=topup_id,
    )
