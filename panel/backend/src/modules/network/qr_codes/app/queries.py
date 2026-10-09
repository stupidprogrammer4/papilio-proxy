import asyncio

from papilio.errors.exceptions import ConflictException, NotFoundException

from src.config.settings import PapilioSettings
from src.modules.network.configurations.interfaces import (
    ISubscriptionFeedQuery,
)
from src.modules.network.qr_codes.app.images import QrImages
from src.modules.network.qr_codes.app.policies import QrCapacity
from src.modules.network.qr_codes.domain.dtos import QrImage
from src.modules.operations.preferences.interfaces import IPreferencesService


class SubscriptionQrQuery:
    def __init__(
        self,
        feed_query: ISubscriptionFeedQuery,
        preferences: IPreferencesService,
        settings: PapilioSettings,
    ) -> None:
        self.feed_query = feed_query
        self.preferences = preferences
        self.settings = settings
        self.images = QrImages()

    async def feed(self, token: str) -> QrImage:
        detail = await self.feed_query.detail(token)
        if detail.feed_url is None:
            raise NotFoundException(
                message="لینک آمادهٔ اتصال پیدا نشد.",
                message_code="subscription_not_found",
                entity="subscription",
                identifier="token",
                identifier_value="redacted",
            )
        policy = (await self.preferences.current()).values.qr_codes
        capacity = self.settings.qr_codes
        if (
            policy is None
            or not policy.enabled
            or capacity is None
            or not QrCapacity.valid(policy, capacity)
        ):
            raise _disabled()
        result = await asyncio.to_thread(
            self.images.render, detail.feed_url, policy, capacity
        )
        return result

    async def profile(
        self, token: str, profile_id: int, host_id: int | None
    ) -> QrImage:
        download = await self.feed_query.profile(token, profile_id, host_id)
        policy = (await self.preferences.current()).values.qr_codes
        capacity = self.settings.qr_codes
        if (
            policy is None
            or not policy.enabled
            or capacity is None
            or not QrCapacity.valid(policy, capacity)
        ):
            raise _disabled()
        result = await asyncio.to_thread(
            self.images.render, download.content, policy, capacity
        )
        return result


def _disabled() -> ConflictException:
    return ConflictException(
        message="دریافت کد تصویری در حال حاضر غیرفعال است.",
        message_code="qr_disabled",
        unique_dict={},
    )
