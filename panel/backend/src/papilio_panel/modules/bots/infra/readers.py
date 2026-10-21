"""Scoped bot read models without exposing credential material."""

from uuid import UUID

from django.core.paginator import EmptyPage, Paginator

from papilio_panel.shared.errors import Conflict, Missing

from ..domain import BotPage, BotRead, BotRuntime, BotSchedule, BotSearch
from ..models import Bot


def bot_read(row: Bot) -> BotRead:
    interval = row.periodic_task.interval
    if interval is None or interval.period != "seconds":
        raise Conflict("This bot requires a native interval measured in seconds.")
    return BotRead(
        id=row.id,
        owner_id=row.owner_id,
        label=row.label,
        revision=row.revision,
        runtime=BotRuntime(
            api_base_url=row.api_base_url,
            poll_timeout_seconds=row.poll_timeout_seconds,
            http_timeout_seconds=row.http_timeout_seconds,
            update_limit=row.update_limit,
            max_response_bytes=row.max_response_bytes,
            pairing_ttl_seconds=row.pairing_ttl_seconds,
            failure_retry_seconds=row.failure_retry_seconds,
        ),
        schedule=BotSchedule(enabled=row.periodic_task.enabled, interval_seconds=interval.every),
        telegram_id=row.telegram_id,
        username=row.username,
        verified=row.telegram_id is not None and row.verified_revision == row.revision,
        admin_chat_id=row.admin_chat_id,
        last_poll_at=row.last_poll_at,
        last_error_code=row.last_error_code,
        next_update_id=row.next_update_id,
        retry_at=row.next_poll_after,
    )


class DjangoBotReader:
    def read(self, bot_id: UUID, actor_id: int) -> BotRead:
        try:
            row = (
                Bot.objects.select_related("periodic_task__interval")
                .defer("token_ciphertext", "token_digest", "input_digest")
                .get(pk=bot_id, owner_id=actor_id)
            )
        except Bot.DoesNotExist as error:
            raise Missing("The bot was not found.") from error
        return bot_read(row)

    def search(self, values: BotSearch) -> BotPage:
        rows = (
            Bot.objects.filter(owner_id=values.actor_id, label__icontains=values.query)
            .select_related("periodic_task__interval")
            .defer("token_ciphertext", "token_digest", "input_digest")
            .order_by("created_at", "id")
        )
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The requested bot page does not exist.") from error
        return BotPage(
            items=tuple(bot_read(row) for row in page.object_list),
            count=paginator.count,
            page=values.page,
            page_size=values.page_size,
        )
