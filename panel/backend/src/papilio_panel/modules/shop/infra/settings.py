"""Native bot-owned shop settings and explicit revision replacement."""

from dataclasses import asdict
from uuid import UUID

from django.db.models import F

from papilio_panel.shared.errors import Conflict, Missing

from ..domain import (
    ShopDefinition,
    ShopFlows,
    ShopSettingsChange,
    ShopSettingsCreate,
    ShopSettingsRead,
    complete_texts,
)
from ..models import ShopConfiguration


def settings_read(row: ShopConfiguration) -> ShopSettingsRead:
    return ShopSettingsRead(
        row.bot_id,
        row.bot.owner_id,
        row.revision,
        ShopDefinition(
            row.public_origin,
            row.enabled,
            row.delivery_enabled,
            row.locale,
            row.page_size,
            row.retry_seconds,
            row.lease_seconds,
            row.max_attempts,
            row.confirmation_ttl_seconds,
            row.ambiguous_delivery,
            complete_texts(row.texts),
            ShopFlows(**row.flows),
            row.welcome_photo_url,
        ),
    )


class DjangoShopSettingsStorage:
    def read(self, bot_id: UUID, actor_id: int) -> ShopSettingsRead:
        try:
            row = ShopConfiguration.objects.select_related("bot").get(
                bot_id=bot_id, bot__owner_id=actor_id
            )
        except ShopConfiguration.DoesNotExist as error:
            raise Missing("Sales are not configured for this bot.") from error
        return settings_read(row)

    def create(self, values: ShopSettingsCreate) -> ShopSettingsRead:
        row, _ = ShopConfiguration.objects.select_related("bot").get_or_create(
            bot_id=values.bot_id, defaults=asdict(values.definition)
        )
        result = settings_read(row)
        if result.definition != values.definition:
            raise Conflict("Shop settings already exist. Read and replace the current revision.")
        return result

    def change(self, values: ShopSettingsChange) -> ShopSettingsRead:
        updated = ShopConfiguration.objects.filter(
            bot_id=values.bot_id, revision=values.expected_revision
        ).update(
            public_origin=values.definition.public_origin,
            enabled=values.definition.enabled,
            delivery_enabled=values.definition.delivery_enabled,
            locale=values.definition.locale,
            page_size=values.definition.page_size,
            retry_seconds=values.definition.retry_seconds,
            lease_seconds=values.definition.lease_seconds,
            max_attempts=values.definition.max_attempts,
            confirmation_ttl_seconds=values.definition.confirmation_ttl_seconds,
            ambiguous_delivery=values.definition.ambiguous_delivery,
            texts=values.definition.texts,
            flows=asdict(values.definition.flows),
            welcome_photo_url=values.definition.welcome_photo_url,
            revision=F("revision") + 1,
        )
        if updated != 1:
            raise Conflict("The shop settings changed. Read the current revision before saving.")
        return self.read(values.bot_id, values.actor_id)
