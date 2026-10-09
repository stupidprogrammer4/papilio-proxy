import asyncio
from datetime import UTC, datetime

from papilio.errors.exceptions import NotFoundException
from papilio.schemas.results import PagedType
from papilio.security.crypto import hash_sha256

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.configurations.app.delivery import ProfileDelivery
from src.modules.network.configurations.domain.dtos import PublicProfileSearch
from src.modules.network.configurations.domain.results import (
    ConfigurationDownload,
    PublicProfile,
    PublicSubscription,
)
from src.modules.network.configurations.infra.mysql import (
    SubscriptionLinkRepository,
)
from src.modules.network.configurations.infra.readers import (
    ConfigurationFactsReader,
)
from src.modules.network.qr_codes.app.policies import QrCapacity
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class SubscriptionFeedQuery:
    def __init__(
        self,
        links: SubscriptionLinkRepository,
        reader: ConfigurationFactsReader,
        settings: PapilioSettings,
        subscriptions: SubscriptionRepository,
        preferences: IPreferencesService,
        customers: ICustomerService,
    ) -> None:
        self.links = links
        self.reader = reader
        self.settings = settings
        self.subscriptions = subscriptions
        self.preferences = preferences
        self.customers = customers
        self.delivery = ProfileDelivery(settings.configuration_encryption_key)

    async def download(self, token: str) -> ConfigurationDownload:
        link = await self.links.by_token(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if link is None:
            raise _missing()
        limit = self.settings.operations.configuration_export_max_profiles
        facts = await self.reader.subscription(link.subscription_id, limit + 1)
        if len(facts) > limit:
            raise _missing()
        now = datetime.now(UTC).replace(tzinfo=None)
        snapshots = [row.detached() for row in facts]
        try:
            result = await asyncio.to_thread(
                self.delivery.feed, snapshots, now
            )
        except ValueError as error:
            raise _missing() from error
        return result

    async def detail(self, token: str) -> PublicSubscription:
        link = await self.links.by_token(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if link is None:
            raise _missing()
        subscription = await self.subscriptions.get_by_id(link.subscription_id)
        if subscription is None:
            raise _missing()
        customer = await self.customers.get(subscription.customer_id)
        preferences = (await self.preferences.current()).values
        capacity = self.settings.operations.configuration_export_max_profiles
        facts = await self.reader.subscription(subscription.id, capacity + 1)
        now = datetime.now(UTC).replace(tzinfo=None)
        snapshots = [row.detached() for row in facts]
        has_feed = len(facts) <= capacity and await asyncio.to_thread(
            self.delivery.has_feed, snapshots, now
        )
        return PublicSubscription(
            qr_enabled=preferences.qr_codes is not None
            and preferences.qr_codes.enabled
            and QrCapacity.valid(preferences.qr_codes, self.settings.qr_codes),
            feed_url=f"{self.settings.public.subscription_origin.rstrip('/')}/s/{token}"
            if has_feed
            else None,
            id=subscription.id,
            status=subscription.status
            if CustomerAccessPolicy.services_available(customer)
            else "customer_hold",
            quota_bytes=subscription.quota_bytes,
            used_bytes=subscription.used_bytes,
            expires_at=subscription.expires_at,
            auto_renew=subscription.auto_renew,
            brand_title=preferences.brand_title,
            support_handle=preferences.support_handle,
        )

    async def profiles(
        self, token: str, data: PublicProfileSearch
    ) -> ServicePage[PublicProfile]:
        link = await self.links.by_token(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if link is None:
            raise _missing()
        capacity = self.settings.operations.configuration_export_max_profiles
        facts = await self.reader.subscription(
            link.subscription_id, capacity + 1
        )
        if len(facts) > capacity:
            raise _missing()
        now = datetime.now(UTC).replace(tzinfo=None)
        available = await asyncio.to_thread(
            self.delivery.available_rows,
            [row.detached() for row in facts],
            now,
        )
        limit = page_size(self.settings, data.per_page)
        offset = (data.page - 1) * limit
        rows = [
            PublicProfile(
                profile_id=row.profile.id,
                host_id=row.host.id if row.host is not None else None,
                label=row.membership.label or row.host.label
                if row.host is not None and row.membership is not None
                else row.configuration.label,
                protocol=row.configuration.protocol,
            )
            for row in available[offset : offset + limit]
        ]
        return service_page(
            PagedType(items=rows, total_items=len(available)), limit
        )

    async def profile(
        self, token: str, profile_id: int, host_id: int | None
    ) -> ConfigurationDownload:
        link = await self.links.by_token(
            (await asyncio.to_thread(hash_sha256, token))
        )
        if link is None:
            raise _missing()
        row = await self.reader.single_profile(
            link.subscription_id, profile_id, host_id
        )
        if row is None:
            raise _missing()
        snapshot = row.detached()
        available = await asyncio.to_thread(
            self.delivery.available,
            snapshot,
            datetime.now(UTC).replace(tzinfo=None),
        )
        if not available:
            raise _missing()
        try:
            result = await asyncio.to_thread(self.delivery.download, snapshot)
        except ValueError as error:
            raise _missing() from error
        return result


def _missing() -> NotFoundException:
    return NotFoundException(
        message="اشتراک یا پروفایل قابل تحویل پیدا نشد.",
        message_code="subscription_unavailable",
        entity="subscription",
        identifier="token",
        identifier_value="redacted",
    )
