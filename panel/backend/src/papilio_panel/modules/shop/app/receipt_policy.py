"""Pure retry decisions for safe read-only receipt transport failures."""

from ..domain import ReceiptDownloadFailure, ShopDefinition

TRANSIENT_DOWNLOAD_ERRORS = frozenset({"connection_failed", "telegram_unavailable", "rate_limited"})


def retry_delay(error: ReceiptDownloadFailure, attempts: int, policy: ShopDefinition) -> int | None:
    if error.transport_code not in TRANSIENT_DOWNLOAD_ERRORS or attempts >= policy.max_attempts:
        return None
    return max(policy.retry_seconds, error.retry_after_seconds or 0)


def exhausted(error_code: str | None, attempts: int, policy: ShopDefinition) -> bool:
    return error_code in TRANSIENT_DOWNLOAD_ERRORS and attempts > policy.max_attempts
