"""Native transactions, conditional leases and set-based durable Telegram inbox."""

import json
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from papilio_panel.config.celery import app
from papilio_panel.shared.credentials import credential_cipher
from papilio_panel.shared.errors import Conflict, Missing

from ..domain import (
    BotChange,
    BotCompletion,
    BotCreate,
    BotCreation,
    BotPollClaim,
    BotPollResult,
    BotRead,
    BotTaskName,
    PairingSecret,
    PairingState,
    TelegramConnection,
)
from ..models import Bot, TelegramInbox
from .readers import DjangoBotReader, bot_read


def poll_task(bot_id: UUID, values: BotCreate) -> PeriodicTask:
    app.autodiscover_tasks(force=True)
    task = app.tasks[BotTaskName.POLL.value]
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=values.schedule.interval_seconds, period="seconds"
    )
    hard_timeout = 3 * values.runtime.http_timeout_seconds + 30
    return PeriodicTask.objects.create(
        name=f"{settings.PAPILIO_NAMESPACE}.bots.{bot_id}.poll",
        task=task.name,
        queue=task.queue,
        kwargs=json.dumps({"bot_id": str(bot_id)}),
        interval=interval,
        enabled=values.schedule.enabled,
        expire_seconds=hard_timeout,
        headers=json.dumps({"timelimit": [hard_timeout, hard_timeout - 5]}),
    )


class DjangoBotStorage(DjangoBotReader):
    def create(self, values: BotCreate, input_digest: str, token_digest: str) -> BotCreation:
        existing = Bot.objects.filter(
            owner_id=values.actor_id, request_key=values.request_key
        ).first()
        if existing is not None:
            return BotCreation(
                bot=self.read(existing.id, values.actor_id), input_digest=existing.input_digest
            )
        identifier = uuid4()
        scheduled = poll_task(identifier, values)
        try:
            row, created = Bot.objects.get_or_create(
                owner_id=values.actor_id,
                request_key=values.request_key,
                defaults={
                    "id": identifier,
                    "input_digest": input_digest,
                    "label": values.label,
                    "periodic_task": scheduled,
                    "token_ciphertext": credential_cipher().encrypt(values.token.encode()),
                    "token_digest": token_digest,
                    **asdict(values.runtime),
                },
            )
        except IntegrityError as error:
            raise Conflict("These bot credentials are already registered.") from error
        if not created:
            scheduled.delete()
        return BotCreation(bot=self.read(row.id, values.actor_id), input_digest=row.input_digest)

    def change(self, values: BotChange, token_digest: str | None = None) -> BotRead:
        try:
            changed = Bot.objects.filter(
                pk=values.bot_id, owner_id=values.actor_id, revision=values.expected_revision
            ).update(
                label=values.label,
                revision=F("revision") + 1,
                verified_revision=None,
                last_error_code=None,
                next_poll_after=None,
                pairing_digest=None,
                pairing_expires_at=None,
                **asdict(values.runtime),
            )
            if changed != 1:
                raise Conflict("The bot changed. Reload its current revision before saving.")
            if values.token is not None:
                Bot.objects.filter(pk=values.bot_id, owner_id=values.actor_id).update(
                    token_ciphertext=credential_cipher().encrypt(values.token.encode()),
                    token_digest=token_digest,
                )
        except IntegrityError as error:
            raise Conflict("These bot credentials are already registered.") from error
        row = Bot.objects.get(pk=values.bot_id, owner_id=values.actor_id)
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=values.schedule.interval_seconds, period="seconds"
        )
        schedule = row.periodic_task
        schedule.interval = interval
        schedule.enabled = values.schedule.enabled
        schedule.expire_seconds = 3 * values.runtime.http_timeout_seconds + 30
        schedule.headers = json.dumps(
            {"timelimit": [schedule.expire_seconds, schedule.expire_seconds - 5]}
        )
        schedule.save(
            update_fields=("interval", "enabled", "expire_seconds", "headers", "date_changed")
        )
        return self.read(values.bot_id, values.actor_id)

    def set_pairing(self, bot: BotRead, secret: PairingSecret) -> None:
        changed = Bot.objects.filter(
            pk=bot.id, owner_id=bot.owner_id, revision=bot.revision, verified_revision=bot.revision
        ).update(pairing_digest=secret.digest, pairing_expires_at=secret.expires_at)
        if changed != 1:
            raise Conflict("The bot changed. Reload it before pairing.")

    def claim(self, bot_id: UUID) -> BotPollClaim | None:
        try:
            row = Bot.objects.select_related("periodic_task__interval").get(pk=bot_id)
        except Bot.DoesNotExist as error:
            raise Missing("The bot was not found.") from error
        now, token = timezone.now(), uuid4()
        changed = Bot.objects.filter(
            Q(lease_until__isnull=True) | Q(lease_until__lt=now),
            Q(next_poll_after__isnull=True) | Q(next_poll_after__lte=now),
            pk=bot_id,
            revision=row.revision,
            periodic_task__enabled=True,
        ).update(
            lease_token=token,
            lease_until=now + timedelta(seconds=3 * row.http_timeout_seconds + 60),
        )
        if not changed:
            return None
        current = (
            Bot.objects.select_related("periodic_task__interval")
            .filter(
                pk=bot_id,
                owner_id=row.owner_id,
                revision=row.revision,
                lease_token=token,
                periodic_task__enabled=True,
            )
            .first()
        )
        if current is None:
            Bot.objects.filter(pk=bot_id, lease_token=token).update(
                lease_token=None, lease_until=None
            )
            return None
        try:
            credential = credential_cipher().decrypt(bytes(current.token_ciphertext)).decode()
        except (InvalidToken, UnicodeError) as error:
            raise Conflict(
                "Stored bot credentials cannot be opened with this installation key."
            ) from error
        public = bot_read(current)
        return BotPollClaim(
            bot=public,
            lease_token=token,
            connection=TelegramConnection(token=credential, runtime=public.runtime),
        )

    def pairing_state(self, claim: BotPollClaim) -> PairingState:
        row = (
            Bot.objects.filter(
                pk=claim.bot.id, owner_id=claim.bot.owner_id, revision=claim.bot.revision
            )
            .values("pairing_digest", "pairing_expires_at")
            .first()
        )
        if row is None:
            return PairingState(digest=None, expires_at=None)
        return PairingState(digest=row["pairing_digest"], expires_at=row["pairing_expires_at"])

    def identity_registration(self, telegram_id: int) -> UUID | None:
        return Bot.objects.filter(telegram_id=telegram_id).values_list("id", flat=True).first()

    def complete(self, claim: BotPollClaim, result: BotPollResult) -> BotCompletion:
        try:
            outcome = self._commit(claim, result)
        except IntegrityError as error:
            cause = error.__cause__
            if (
                getattr(getattr(cause, "diag", None), "constraint_name", None)
                != "bots_telegram_identity"
            ):
                raise
            outcome = BotCompletion.IDENTITY_CONFLICT
        return outcome

    @transaction.atomic
    def _commit(self, claim: BotPollClaim, result: BotPollResult) -> BotCompletion:
        changed = Bot.objects.filter(
            pk=claim.bot.id,
            owner_id=claim.bot.owner_id,
            revision=claim.bot.revision,
            lease_token=claim.lease_token,
        ).update(
            telegram_id=result.identity.id,
            username=result.identity.username,
            verified_revision=claim.bot.revision,
            next_update_id=result.next_update_id,
            last_poll_at=result.observed_at,
            last_error_code=None,
            next_poll_after=None,
            lease_token=None,
            lease_until=None,
        )
        if not changed:
            Bot.objects.filter(pk=claim.bot.id, lease_token=claim.lease_token).update(
                lease_token=None, lease_until=None
            )
            return BotCompletion.STALE
        TelegramInbox.objects.bulk_create(
            [
                TelegramInbox(
                    bot_id=claim.bot.id, update_id=update.update_id, payload=update.payload
                )
                for update in result.updates
            ],
            ignore_conflicts=True,
        )
        if result.paired_chat_id is not None:
            Bot.objects.filter(
                pk=claim.bot.id,
                owner_id=claim.bot.owner_id,
                pairing_digest=result.pairing_digest,
                pairing_expires_at__gt=timezone.now(),
            ).update(
                admin_chat_id=result.paired_chat_id, pairing_digest=None, pairing_expires_at=None
            )
        return BotCompletion.COMMITTED

    @transaction.atomic
    def fail(
        self, claim: BotPollClaim, error_code: str, retry_after_seconds: int | None = None
    ) -> None:
        now = timezone.now()
        delay = max(claim.bot.runtime.failure_retry_seconds, retry_after_seconds or 0)
        Bot.objects.filter(
            pk=claim.bot.id, revision=claim.bot.revision, lease_token=claim.lease_token
        ).update(
            last_poll_at=now,
            next_poll_after=now + timedelta(seconds=delay),
            last_error_code=error_code,
            lease_token=None,
            lease_until=None,
        )
        Bot.objects.filter(pk=claim.bot.id, lease_token=claim.lease_token).update(
            lease_token=None, lease_until=None
        )
