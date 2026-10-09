from papilio.security.crypto import secure_compare

from src.config.settings import PapilioSettings


def admin_origin_allowed(origin: str, settings: PapilioSettings) -> bool:
    allowed = [
        settings.public.admin_origin,
        *settings.public.additional_admin_origins,
    ]
    return (
        bool(origin)
        and origin.isascii()
        and any(
            item.isascii() and secure_compare(origin, item) for item in allowed
        )
    )
