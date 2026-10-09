from io import BytesIO

from papilio.errors.exceptions import ConflictException
from qrcode import QRCode, constants
from qrcode.exceptions import DataOverflowError
from qrcode.image.pil import PilImage

from src.config.settings import QrSettings
from src.modules.network.qr_codes.domain.dtos import QrImage, QrPolicy


class QrImages:
    def render(
        self, payload: str, policy: QrPolicy, capacity: QrSettings
    ) -> QrImage:
        if len(payload.encode()) > capacity.max_payload_bytes:
            raise _capacity()
        correction = {
            "L": constants.ERROR_CORRECT_L,
            "M": constants.ERROR_CORRECT_M,
            "Q": constants.ERROR_CORRECT_Q,
            "H": constants.ERROR_CORRECT_H,
        }[policy.error_correction]
        qr = QRCode(
            error_correction=correction,
            box_size=policy.box_size,
            border=policy.border_modules,
        )
        qr.add_data(payload)
        try:
            qr.make(fit=True)
        except DataOverflowError as error:
            raise _capacity() from error
        if (
            qr.modules_count + 2 * policy.border_modules
        ) * policy.box_size > capacity.max_side_pixels:
            raise _capacity()
        output = BytesIO()
        qr.make_image(image_factory=PilImage).save(output)
        content = output.getvalue()
        if len(content) > capacity.max_png_bytes:
            raise _capacity()
        return QrImage(content=content, filename="connection-qr.png")


def _capacity() -> ConflictException:
    return ConflictException(
        message="ظرفیت کد تصویری کافی نیست؛ از لینک یا فایل استفاده کنید.",
        message_code="qr_render_capacity",
        unique_dict={},
    )
