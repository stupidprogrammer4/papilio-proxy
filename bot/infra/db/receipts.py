from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from bot.infra.db.models import Base, PaymentAttemptModel, SubscriptionModel
from bot.infra.db.pool import create_mysql_engine
from bot.infra.db.user_access import subscription_user_is_allowed
from bot.models.receipts import ReceiptOrder, ReceiptUnavailable
from bot.models.subscriptions import SubscriptionStatus


class ReceiptPolicyModel(Base):
    __tablename__ = "receipt_policy"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class ReceiptSubmissionModel(Base):
    __tablename__ = "receipt_submissions"
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscriptions.id"), primary_key=True,
    )
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    uploaded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None),
    )


class MysqlReceiptRepository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    async def enabled(self) -> bool:
        async with self._session_factory() as session:
            row = await session.get(ReceiptPolicyModel, 1)
            return row is not None and row.enabled

    async def set_enabled(self, enabled: bool) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(ReceiptPolicyModel, 1, with_for_update=True)
            if row is None:
                session.add(ReceiptPolicyModel(id=1, enabled=enabled))
            else:
                row.enabled = enabled

    @staticmethod
    def _eligible():
        return select(PaymentAttemptModel).join(
            SubscriptionModel, SubscriptionModel.id == PaymentAttemptModel.order_id,
        ).where(
            PaymentAttemptModel.status == "pending",
            SubscriptionModel.status == SubscriptionStatus.PENDING_PAYMENT.value,
            subscription_user_is_allowed(),
        )

    async def bound_order(self, authority: str) -> ReceiptOrder | None:
        async with self._session_factory() as session:
            row = await session.scalar(self._eligible().where(
                PaymentAttemptModel.authority == authority,
                PaymentAttemptModel.amount_rial == SubscriptionModel.price_rial,
            ))
            if row is None:
                return None
            return ReceiptOrder(row.order_id, row.authority, row.provider_transaction_id, row.amount_rial)

    async def reserve(self, order_id: str, digest: str) -> bool:
        """Persist only an image hash, never a bank receipt or banking credentials."""
        try:
            async with self._session_factory() as session, session.begin():
                row = await session.get(ReceiptSubmissionModel, order_id, with_for_update=True)
                if row is not None:
                    if row.digest != digest:
                        raise ReceiptUnavailable("برای این سفارش قبلاً رسید ثبت شده است.")
                    return row.uploaded
                session.add(ReceiptSubmissionModel(order_id=order_id, digest=digest, uploaded=False))
                return False
        except IntegrityError as exc:
            raise ReceiptUnavailable("این رسید قبلاً ثبت شده است؛ دوباره پرداخت نکن.") from exc

    async def mark_uploaded(self, order_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(ReceiptSubmissionModel, order_id, with_for_update=True)
            if row is None:
                raise ReceiptUnavailable("رسید به سفارش متصل نشد.")
            row.uploaded = True

    async def pending_uploads(self, limit: int = 5) -> list[str]:
        async with self._session_factory() as session:
            statement = self._eligible().join(
                ReceiptSubmissionModel, ReceiptSubmissionModel.order_id == PaymentAttemptModel.order_id,
            ).where(ReceiptSubmissionModel.uploaded.is_(True)).order_by(
                ReceiptSubmissionModel.created_at,
            ).limit(max(1, min(limit, 20)))
            return [row.authority for row in (await session.scalars(statement)).all()]
