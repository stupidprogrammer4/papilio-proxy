import asyncio
import hashlib

from src.modules.sales.checkout.app.errors import checkout_conflict
from src.modules.sales.checkout.domain.contracts import (
    CheckoutCancel,
    CheckoutReconfirm,
)
from src.modules.sales.checkout.domain.models import (
    CheckoutActionReceiptModel,
    CheckoutIntentModel,
)
from src.modules.sales.checkout.infra.mysql import (
    CheckoutActionReceiptRepository,
)


class CheckoutActionReceiptService:
    def __init__(self, receipts: CheckoutActionReceiptRepository) -> None:
        self.receipts = receipts

    @staticmethod
    def digest(data: CheckoutReconfirm | CheckoutCancel) -> str:
        return hashlib.sha256(data.model_dump_json().encode()).hexdigest()

    async def replay(
        self,
        row: CheckoutIntentModel,
        action: str,
        data: CheckoutReconfirm | CheckoutCancel,
    ) -> tuple[str, str, bool]:
        key = f"checkout-action:{row.customer_id}:{data.request_key}"
        digest = await asyncio.to_thread(self.digest, data)
        receipt = await self.receipts.by_key_current(key)
        if receipt is not None:
            if (
                receipt.intent_id != row.id
                or receipt.customer_id != row.customer_id
                or receipt.action != action
                or receipt.body_sha256 != digest
            ):
                raise checkout_conflict(
                    "checkout_action_request_conflict", row.id
                )
            return key, digest, True
        return key, digest, False

    async def record(
        self, row: CheckoutIntentModel, action: str, key: str, digest: str
    ) -> None:
        await self.receipts.create(
            CheckoutActionReceiptModel(
                intent_id=row.id,
                customer_id=row.customer_id,
                request_key=key,
                action=action,
                body_sha256=digest,
                accepted_revision=row.revision,
            )
        )
