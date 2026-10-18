import asyncio
import base64
from typing import Literal

from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import decrypt, encrypt

from src.config.settings import PapilioSettings
from src.modules.billing.receipts.app.extraction_parsing import (
    ReceiptExtractionParser,
)
from src.modules.billing.receipts.app.ocr_interfaces import IReceiptOcrApi
from src.modules.billing.receipts.domain.extraction import (
    ReceiptExtractionFields,
)
from src.modules.billing.receipts.domain.models import PaymentReceiptModel
from src.modules.billing.receipts.infra.mysql import PaymentReceiptRepository


class PaymentReceiptOcrCommand:
    def __init__(
        self,
        repo: PaymentReceiptRepository,
        settings: PapilioSettings,
        ocr: IReceiptOcrApi,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.ocr = ocr

    async def process(self, receipt_id: int) -> None:
        receipt = await self.repo.get_by_id(receipt_id)
        if receipt is None:
            raise receipt_missing(receipt_id)
        if receipt.encrypted_extraction is None:
            extraction, status = await self._extract(receipt)
            ciphertext = await asyncio.to_thread(
                encrypt,
                extraction.model_dump_json(),
                self.settings.configuration_encryption_key,
            )
            await self._store(receipt.id, ciphertext, status)

    async def _extract(
        self, receipt: PaymentReceiptModel
    ) -> tuple[ReceiptExtractionFields, Literal["complete", "failed"]]:
        plaintext = await asyncio.to_thread(
            decrypt,
            receipt.encrypted_payload,
            self.settings.configuration_encryption_key,
        )
        content = await asyncio.to_thread(
            base64.b64decode, plaintext, validate=True
        )
        result = await self.ocr.recognize(content)
        if result.failure_code is not None:
            extraction = ReceiptExtractionFields(
                reason_codes=(result.failure_code,)
            )
            status = "failed"
        else:
            extraction = ReceiptExtractionParser.parse(result.lines)
            status = "complete"
        return extraction, status

    @transactional
    async def _store(
        self,
        receipt_id: int,
        ciphertext: str,
        status: Literal["complete", "failed"],
    ) -> None:
        await self.repo.store_extraction(receipt_id, ciphertext, status)


def receipt_missing(receipt_id: int) -> NotFoundException:
    return NotFoundException(
        message="رسید پیدا نشد.",
        message_code="payment_receipt_not_found",
        entity="receipt",
        identifier="id",
        identifier_value=receipt_id,
    )
