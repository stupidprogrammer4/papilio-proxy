"""Pure delivery outcomes preserve unknown sends separately from safe failures."""

from papilio_panel.modules.bots.domain import TelegramSendResult

from ..domain import MessageState, SendDisposition, ShopDefinition


def disposition(
    result: TelegramSendResult, attempts: int, settings: ShopDefinition
) -> SendDisposition:
    if result.error_code is None:
        return SendDisposition(MessageState.SENT)
    if result.ambiguous and settings.ambiguous_delivery == "hold":
        return SendDisposition(MessageState.AMBIGUOUS)
    if result.error_code in {"invalid_input", "invalid_credentials", "not_found"}:
        return SendDisposition(MessageState.FAILED)
    if attempts >= settings.max_attempts:
        return SendDisposition(MessageState.FAILED)
    return SendDisposition(
        MessageState.RETRY, max(settings.retry_seconds, result.retry_after_seconds or 0)
    )
