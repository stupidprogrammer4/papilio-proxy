from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import NotFoundException
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.billing.reviews.domain.models import PaymentReviewModel
from src.modules.billing.reviews.infra.mysql import PaymentReviewRepository
from src.modules.billing.reviews.infra.readers import PaymentReviewReader
from src.modules.billing.wallet.infra.mysql import TopupRepository
from src.modules.operations.preferences.interfaces import IPreferencesService


class PaymentReviewCommand:
    def __init__(
        self,
        topups: TopupRepository,
        reviews: PaymentReviewRepository,
        reader: PaymentReviewReader,
        settings: PapilioSettings,
        preferences: IPreferencesService,
    ) -> None:
        self.topups = topups
        self.reviews = reviews
        self.reader = reader
        self.settings = settings
        self.preferences = preferences

    @transactional
    async def check(self, topup_id: int) -> PaymentReviewModel:
        # Serialize snapshots with approval so a closed payment stays closed.
        topup = await self.topups.locked(topup_id)
        if topup is None:
            raise NotFoundException(
                message="درخواست شارژ پیدا نشد.",
                message_code="topup_not_found",
                entity="topup",
                identifier="id",
                identifier_value=topup_id,
            )
        now = datetime.now(UTC).replace(tzinfo=None)
        policy = self.settings.operations
        preferences = (await self.preferences.current()).values
        candidate_count, competing_count = 0, 0
        if topup.status != "pending":
            status = "closed"
        else:
            assert topup.created_at is not None
            since = max(
                now - timedelta(hours=policy.sms_match_window_hours),
                topup.created_at
                - timedelta(minutes=policy.sms_match_before_topup_minutes),
            )
            facts = await self.reader.match_facts(
                topup_id, topup.amount_rial, since, now, "pending", "approved"
            )
            candidate_count, competing_count = (
                facts.candidate_count,
                facts.competing_topup_count,
            )
            if candidate_count > 1 or (candidate_count and competing_count):
                status = "ambiguous"
            elif candidate_count:
                status = "candidate"
            elif topup.created_at <= now - timedelta(
                hours=preferences.payment_stale_hours
            ):
                status = "stale"
            else:
                status = "waiting"
        result = await self.reviews.store(
            PaymentReviewModel(
                topup_id=topup_id,
                status=status,
                candidate_count=candidate_count,
                competing_topup_count=competing_count,
                checked_at=now,
            )
        )
        return result
