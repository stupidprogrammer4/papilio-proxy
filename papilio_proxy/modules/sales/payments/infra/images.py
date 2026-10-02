import asyncio
import io
import warnings

from PIL import Image, UnidentifiedImageError

from papilio_proxy.modules.sales.payments.domain.entities import PaymentError

MAX_RECEIPT_BYTES = 5 * 1024 * 1024


def _sanitize(image: bytes) -> bytes:
    if not image or len(image) > MAX_RECEIPT_BYTES:
        raise PaymentError("عکس رسید باید حداکثر ۵ مگابایت باشد.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image)) as source:
                if (
                    source.format not in {"JPEG", "PNG", "WEBP"}
                    or source.width * source.height > 16_000_000
                ):
                    raise PaymentError("عکس رسید باید JPG، PNG یا WebP با ابعاد مناسب باشد.")
                source.load()
                output = io.BytesIO()
                source.convert("RGB").save(output, format="JPEG", quality=90)
                cleaned = output.getvalue()
                if len(cleaned) > MAX_RECEIPT_BYTES:
                    raise PaymentError("حجم عکس رسید بیش از حد مجاز است.")
                return cleaned
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise PaymentError("عکس رسید خوانا نیست؛ لطفاً عکس دیگری بفرست.") from exc


async def sanitize_receipt(image: bytes) -> bytes:
    return await asyncio.to_thread(_sanitize, image)
