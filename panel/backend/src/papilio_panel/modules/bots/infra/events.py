"""Native retained-message facts and current scoped transport credentials."""

from uuid import UUID

from cryptography.fernet import InvalidToken
from django.db.models.functions import Coalesce
from django.utils import timezone

from papilio_panel.shared.credentials import credential_cipher
from papilio_panel.shared.errors import Conflict, Missing

from ..domain import BotEventRead, PrivateMessage, TelegramConnection, TelegramFileReference
from ..models import Bot, TelegramInbox
from .readers import bot_read
from .telegram_payload import TelegramPayloadSerializer


def private_message(payload: dict, bot_telegram_id: int | None) -> PrivateMessage | None:
    serializer = TelegramPayloadSerializer(data=payload)
    if not serializer.is_valid():
        raise Conflict("The retained Telegram event has invalid protocol fields.")
    values = serializer.validated_data
    callback = values.get("callback_query")
    source = callback.get("message") if callback is not None else values.get("message")
    sender = callback.get("from") if callback is not None else (source or {}).get("from")
    if source is None or sender is None:
        return None
    chat = source["chat"]
    if chat["type"] != "private" or chat["id"] != sender["id"] or sender.get("is_bot") is True:
        return None
    if callback is not None and source.get("from", {}).get("id") != bot_telegram_id:
        return None
    text = source.get("text", source.get("caption", "")) if callback is None else ""
    attachment = source.get("document")
    if attachment is None and source.get("photo"):
        attachment = max(
            source["photo"],
            key=lambda item: item.get("file_size", item.get("width", 0) * item.get("height", 0)),
        )
    file = None
    if attachment is not None:
        file = TelegramFileReference(
            attachment["file_id"],
            attachment.get("file_name", "receipt.jpg"),
            attachment.get("mime_type", "image/jpeg"),
            attachment.get("file_size"),
        )
    name = " ".join(
        part for part in (sender.get("first_name", ""), sender.get("last_name", "")) if part
    ).strip()
    return PrivateMessage(
        sender["id"],
        chat["id"],
        name,
        text,
        callback.get("id") if callback else None,
        callback.get("data") if callback else None,
        source.get("reply_to_message", {}).get("message_id"),
        file,
    )


class DjangoBotEventStorage:
    def read(self, event_id: int) -> BotEventRead:
        try:
            row = (
                TelegramInbox.objects.select_related("bot__periodic_task__interval")
                .defer("bot__token_ciphertext", "bot__token_digest", "bot__input_digest")
                .get(pk=event_id)
            )
        except TelegramInbox.DoesNotExist as error:
            raise Missing("The incoming Telegram event was not found.") from error
        bot = bot_read(row.bot)
        return BotEventRead(
            row.pk,
            bot,
            row.update_id,
            private_message(row.payload, bot.telegram_id),
            row.processed_at,
        )

    def processed(self, event_id: int, bot_id: UUID, owner_id: int) -> None:
        updated = TelegramInbox.objects.filter(
            pk=event_id, bot_id=bot_id, bot__owner_id=owner_id
        ).update(processed_at=Coalesce("processed_at", timezone.now()))
        if updated != 1:
            raise Missing("The incoming Telegram event was not found on this bot.")

    def connection(self, bot_id: UUID, owner_id: int, revision: int) -> TelegramConnection:
        try:
            row = Bot.objects.select_related("periodic_task__interval").get(
                pk=bot_id,
                owner_id=owner_id,
                revision=revision,
                verified_revision=revision,
                periodic_task__enabled=True,
            )
        except Bot.DoesNotExist as error:
            raise Conflict("The bot is paused, changed or not verified.") from error
        try:
            token = credential_cipher().decrypt(bytes(row.token_ciphertext)).decode()
        except (InvalidToken, UnicodeError) as error:
            raise Conflict(
                "Stored bot credentials cannot be opened with this installation key."
            ) from error
        return TelegramConnection(token, bot_read(row).runtime)
