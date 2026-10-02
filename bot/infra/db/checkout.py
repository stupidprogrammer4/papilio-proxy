from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.checkout_models import CheckoutReservationModel, CheckoutSettingsModel
from bot.infra.db.models import Base, PaymentAttemptModel, SubscriptionModel
from bot.infra.db.pool import create_mysql_engine
from bot.models.checkout import CheckoutConfig, CheckoutOrder, CheckoutUnavailable
from bot.models.payments import PaymentInitiation


class MysqlCheckoutRepository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self._session_factory() as session, session.begin():
            await session.execute(insert(CheckoutSettingsModel).values(id=1).prefix_with("IGNORE"))

    async def close(self) -> None:
        await self._engine.dispose()

    async def get_config(self) -> CheckoutConfig:
        async with self._session_factory() as session:
            value = await session.get(CheckoutSettingsModel, 1)
        if value is None:
            return CheckoutConfig()
        return CheckoutConfig(value.enabled, value.shop_id, value.card_id, value.callback_url)

    async def save_config(self, value: CheckoutConfig) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(CheckoutSettingsModel, 1, with_for_update=True)
            if row is None:
                row = CheckoutSettingsModel(id=1)
                session.add(row)
            row.enabled, row.shop_id, row.card_id, row.callback_url = (
                value.enabled, value.shop_id, value.card_id, value.callback_url
            )

    async def get_order(self, telegram_id: int, order_id: str) -> CheckoutOrder | None:
        statement = (
            select(SubscriptionModel, PaymentAttemptModel)
            .outerjoin(PaymentAttemptModel, PaymentAttemptModel.order_id == SubscriptionModel.id)
            .where(SubscriptionModel.id == order_id, SubscriptionModel.telegram_id == telegram_id)
        )
        async with self._session_factory() as session:
            pair = (await session.execute(statement)).one_or_none()
        if pair is None:
            return None
        order, attempt = pair
        checkout = PaymentInitiation(
            attempt.provider_transaction_id, attempt.authority, attempt.amount_rial,
            attempt.payment_url,
        ) if attempt else None
        return CheckoutOrder(order.id, order.price_rial, order.status, checkout)

    async def claim(self, order_id: str) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                session.add(CheckoutReservationModel(order_id=order_id))
        except IntegrityError as exc:
            raise CheckoutUnavailable("وضعیت پرداخت قبلی نامشخص است؛ با پشتیبانی تماس بگیر.") from exc
