from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import NotFoundException

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.billing.sms.domain.models import SmsEventModel
from src.modules.billing.sms.infra.readers import SmsCandidateReader
from src.modules.billing.wallet.infra.mysql import TopupRepository


class SmsCandidateQuery:
    def __init__(
        self,
        topups: TopupRepository,
        reader: SmsCandidateReader,
        settings: PapilioSettings,
    ) -> None:
        self.topups = topups
        self.reader = reader
        self.settings = settings

    async def for_topup(
        self, topup_id: int, page: int, per_page: int | None
    ) -> ServicePage[SmsEventModel]:
        topup = await self.topups.get_by_id(topup_id)
        if topup is None:
            raise NotFoundException(
                message="درخواست شارژ پیدا نشد.",
                message_code="topup_not_found",
                entity="topup",
                identifier="id",
                identifier_value=topup_id,
            )
        limit = page_size(self.settings, per_page)
        if topup.status != "pending":
            return ServicePage((), 0, limit)
        if topup.created_at is None:
            raise RuntimeError("Persisted top-up has no creation time")
        policy = self.settings.operations
        now = datetime.now(UTC).replace(tzinfo=None)
        since = max(
            now - timedelta(hours=policy.sms_match_window_hours),
            topup.created_at
            - timedelta(minutes=policy.sms_match_before_topup_minutes),
        )
        result = await self.reader.for_topup(
            topup.amount_rial,
            since,
            now,
            (page - 1) * limit,
            limit,
            "approved",
        )
        return service_page(result, limit)
