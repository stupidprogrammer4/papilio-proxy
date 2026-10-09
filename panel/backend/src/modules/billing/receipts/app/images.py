from io import BytesIO

from anyio import CapacityLimiter, WouldBlock, to_thread
from papilio.errors.exceptions import ConflictException
from PIL import Image, UnidentifiedImageError

from src.config.settings import ReceiptSettings
from src.modules.billing.receipts.domain.dtos import ReceiptPolicy
from src.modules.billing.receipts.domain.results import ReceiptDownload


class ReceiptImages:
    def __init__(self, settings: ReceiptSettings) -> None:
        self.settings = settings
        self.slots = CapacityLimiter(settings.max_concurrent_images)

    async def process(
        self, content: bytes, policy: ReceiptPolicy
    ) -> ReceiptDownload:
        try:
            self.slots.acquire_nowait()
        except WouldBlock as error:
            raise ConflictException(
                message="پردازش رسیدها مشغول است؛ دوباره تلاش کنید.",
                message_code="receipt_busy",
                unique_dict={},
            ) from error
        try:
            result = await to_thread.run_sync(self.normalize, content, policy)
            return result
        finally:
            self.slots.release()

    def normalize(
        self, content: bytes, policy: ReceiptPolicy
    ) -> ReceiptDownload:
        try:
            image = Image.open(BytesIO(content))
            if (
                image.format not in policy.allowed_formats
                or image.width * image.height > self.settings.max_pixels
            ):
                raise ValueError("Unsupported receipt image")
            image.verify()
            image = Image.open(BytesIO(content))
            image.load()
            # Strip EXIF and extra payloads by re-encoding pixels.
            output = BytesIO()
            pixels = image.convert("RGB")
            pixels.save(
                output, format="JPEG", quality=self.settings.jpeg_quality
            )
            normalized = output.getvalue()
            if len(normalized) > self.settings.max_image_bytes:
                raise ValueError("Receipt too large")
            return ReceiptDownload(content=normalized, media_type="image/jpeg")
        except (
            ValueError,
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as error:
            raise ConflictException(
                message="تصویر رسید معتبر نیست یا بیش از حد مجاز است.",
                message_code="receipt_image_invalid",
                unique_dict={},
            ) from error
