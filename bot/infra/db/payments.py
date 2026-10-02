from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.models import Base, PaymentAttemptModel, SubscriptionModel
from bot.infra.db.pool import create_mysql_engine
from bot.models.payments import PaymentInitiation, ProviderVerification
from bot.models.subscriptions import SubscriptionStatus
from bot.services.payments import PaymentSettlementError


def _paid_datetime(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PaymentSettlementError("Invalid provider settlement time") from exc
    if timestamp.tzinfo is None:
        raise PaymentSettlementError("Provider settlement time has no timezone")
    return timestamp.astimezone(UTC).replace(tzinfo=None)


class MysqlPaymentRepository:
    """All payment/order comparisons and state changes occur inside one MySQL transaction."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    async def order_id_for_authority(self, authority: str) -> str | None:
        async with self._session_factory() as session:
            return await session.scalar(select(PaymentAttemptModel.order_id).where(
                PaymentAttemptModel.authority == authority
            ))

    async def pending_authorities(self, after: str | None, limit: int) -> list[str]:
        statement = (
            select(PaymentAttemptModel.authority)
            .join(SubscriptionModel, SubscriptionModel.id == PaymentAttemptModel.order_id)
            .where(PaymentAttemptModel.status == "pending",
                   SubscriptionModel.status == SubscriptionStatus.PENDING_PAYMENT.value)
            .order_by(PaymentAttemptModel.authority).limit(max(1, min(limit, 20)))
        )
        if after:
            statement = statement.where(PaymentAttemptModel.authority > after)
        async with self._session_factory() as session:
            return list((await session.scalars(statement)).all())

    async def has_authority(self, authority: str) -> bool:
        statement = select(PaymentAttemptModel.order_id).where(
            PaymentAttemptModel.authority == authority
        )
        async with self._session_factory() as session:
            return (await session.scalar(statement)) is not None

    async def attach_checkout(self, order_id: str, checkout: PaymentInitiation) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                order = await session.scalar(
                    select(SubscriptionModel)
                    .where(SubscriptionModel.id == order_id)
                    .with_for_update()
                )
                if (
                    order is None
                    or order.status != SubscriptionStatus.PENDING_PAYMENT.value
                    or order.price_rial != checkout.amount_rial
                ):
                    raise PaymentSettlementError("Checkout does not match a pending order")
                session.add(
                    PaymentAttemptModel(
                        order_id=order_id,
                        authority=checkout.authority,
                        provider_transaction_id=checkout.transaction_id,
                        amount_rial=checkout.amount_rial,
                        payment_url=checkout.payment_url,
                        status="pending",
                        paid_at=None,
                    )
                )
        except IntegrityError as exc:
            raise PaymentSettlementError("Checkout already attached or provider ID reused") from exc

    async def settle_verified(self, result: ProviderVerification) -> bool:
        if not result.verified or result.paid_at is None:
            raise PaymentSettlementError("Provider has not settled the payment")
        paid_at = _paid_datetime(result.paid_at)
        async with self._session_factory() as session, session.begin():
            attempt = await session.scalar(
                select(PaymentAttemptModel)
                .where(PaymentAttemptModel.authority == result.authority)
                .with_for_update()
            )
            if attempt is None:
                return False
            order = await session.scalar(
                select(SubscriptionModel)
                .where(SubscriptionModel.id == attempt.order_id)
                .with_for_update()
            )
            if (
                order is None
                or attempt.provider_transaction_id != result.transaction_id
                or attempt.amount_rial != result.amount_rial
                or order.price_rial != result.amount_rial
            ):
                raise PaymentSettlementError("Provider payment does not match this order")
            if attempt.status == "paid":
                valid_paid_states = {
                    SubscriptionStatus.PAID_AWAITING_PROVISIONING.value,
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.EXPIRED.value,
                    SubscriptionStatus.SUSPENDED.value,
                }
                if order.status not in valid_paid_states:
                    raise PaymentSettlementError("Previously settled order has inconsistent state")
                return True
            if (
                attempt.status != "pending"
                or order.status != SubscriptionStatus.PENDING_PAYMENT.value
            ):
                raise PaymentSettlementError("Order state cannot be settled")
            attempt.status = "paid"
            attempt.paid_at = paid_at
            order.status = SubscriptionStatus.PAID_AWAITING_PROVISIONING.value
            return True
