import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from papilio_proxy.config.database import Base, DatabaseConnection, create_mysql_engine
from papilio_proxy.modules.accounts.users.infra.repository import require_user_access
from papilio_proxy.modules.accounts.users.infra.tables import UserModel
from papilio_proxy.modules.sales.payments.domain.entities import (
    PaymentError,
    PaymentInstructions,
    PaymentKind,
    PaymentMethod,
    PaymentReceipt,
    ReceiptNotification,
    ReceiptStatus,
)
from papilio_proxy.modules.sales.payments.infra.images import sanitize_receipt
from papilio_proxy.modules.sales.payments.infra.tables import (
    CardPaymentOrderModel,
    ManualSettlementModel,
    PaymentMethodModel,
    PaymentReceiptModel,
)
from papilio_proxy.modules.sales.subscriptions.domain.entities import Protocol, SubscriptionStatus
from papilio_proxy.modules.sales.subscriptions.infra.tables import (
    PlanModel,
    SubscriptionModel,
    SubscriptionTermsModel,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _method(row: PaymentMethodModel) -> PaymentMethod:
    return PaymentMethod(
        row.id,
        PaymentKind(row.kind),
        row.title,
        row.card_number,
        row.bank_name,
        row.account_holder,
        row.enabled,
    )


def _instructions(
    order: SubscriptionModel, destination: CardPaymentOrderModel, title: str
) -> PaymentInstructions:
    return PaymentInstructions(
        order.id,
        order.price_rial,
        title,
        destination.method_title,
        destination.card_number,
        destination.bank_name,
        destination.account_holder,
    )


class MysqlPaymentRepository:
    """Payment queries, immutable destinations, encrypted receipts and atomic review."""

    def __init__(self, database_url: str | DatabaseConnection, encryption_key: str) -> None:
        self._owns_engine = isinstance(database_url, str)
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._cipher = Fernet(encryption_key.encode())

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        if self._owns_engine:
            await self._engine.dispose()

    async def methods(self, *, enabled_only: bool = False) -> list[PaymentMethod]:
        statement = select(PaymentMethodModel).order_by(
            PaymentMethodModel.title, PaymentMethodModel.id
        )
        if enabled_only:
            statement = statement.where(PaymentMethodModel.enabled.is_(True))
        async with self._session_factory() as session:
            return [_method(row) for row in await session.scalars(statement)]

    async def save_method(self, method: PaymentMethod) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(PaymentMethodModel, method.id, with_for_update=True)
            if row is None:
                row = PaymentMethodModel(id=method.id)
                session.add(row)
            row.kind, row.title, row.card_number = (
                method.kind.value,
                method.title,
                method.card_number,
            )
            row.bank_name, row.account_holder, row.enabled = (
                method.bank_name,
                method.account_holder,
                method.enabled,
            )

    async def begin(self, telegram_id: int, plan_code: str, method_id: str) -> PaymentInstructions:
        async with self._session_factory() as session, session.begin():
            user = await session.get(UserModel, telegram_id, with_for_update=True)
            if user is None:
                raise PaymentError("ابتدا بات را شروع کن.")
            await require_user_access(session, telegram_id)
            plan = await session.get(PlanModel, plan_code)
            method = await session.get(PaymentMethodModel, method_id, with_for_update=True)
            if plan is None or not plan.is_active:
                raise PaymentError("این پلن در دسترس نیست.")
            if (
                method is None
                or not method.enabled
                or method.kind != PaymentKind.CARD_TO_CARD.value
            ):
                raise PaymentError("این روش پرداخت در دسترس نیست.")
            existing = await session.execute(
                select(SubscriptionModel, CardPaymentOrderModel)
                .join(CardPaymentOrderModel, CardPaymentOrderModel.order_id == SubscriptionModel.id)
                .join(
                    SubscriptionTermsModel,
                    SubscriptionTermsModel.subscription_id == SubscriptionModel.id,
                )
                .where(
                    SubscriptionModel.telegram_id == telegram_id,
                    SubscriptionModel.plan_code == plan.code,
                    SubscriptionModel.status == SubscriptionStatus.PENDING_PAYMENT.value,
                    SubscriptionModel.price_rial == plan.price_rial,
                    SubscriptionModel.traffic_limit_bytes == plan.traffic_gb * 1024**3,
                    SubscriptionTermsModel.duration_days == plan.duration_days,
                    CardPaymentOrderModel.method_id == method.id,
                )
                .order_by(SubscriptionModel.created_at.desc())
                .limit(1)
            )
            pair = existing.one_or_none()
            if pair:
                order, destination = pair
            else:
                order = SubscriptionModel(
                    id=str(uuid4()),
                    telegram_id=telegram_id,
                    plan_code=plan.code,
                    protocol=Protocol.BOTH.value,
                    status=SubscriptionStatus.PENDING_PAYMENT.value,
                    price_rial=plan.price_rial,
                    traffic_limit_bytes=plan.traffic_gb * 1024**3,
                    traffic_used_bytes=0,
                    expires_at=None,
                    created_at=_now(),
                )
                session.add(order)
                await session.flush()
                session.add(
                    SubscriptionTermsModel(
                        subscription_id=order.id, duration_days=plan.duration_days
                    )
                )
                destination = CardPaymentOrderModel(
                    order_id=order.id,
                    method_id=method.id,
                    method_title=method.title,
                    card_number=method.card_number,
                    bank_name=method.bank_name,
                    account_holder=method.account_holder,
                )
                session.add(destination)
            return _instructions(order, destination, plan.title)

    async def instructions(self, telegram_id: int, order_id: str) -> PaymentInstructions:
        async with self._session_factory() as session:
            await require_user_access(session, telegram_id)
            pair = (
                await session.execute(
                    select(SubscriptionModel, CardPaymentOrderModel, PlanModel.title)
                    .join(
                        CardPaymentOrderModel,
                        CardPaymentOrderModel.order_id == SubscriptionModel.id,
                    )
                    .outerjoin(PlanModel, PlanModel.code == SubscriptionModel.plan_code)
                    .where(
                        SubscriptionModel.id == order_id,
                        SubscriptionModel.telegram_id == telegram_id,
                        SubscriptionModel.status == SubscriptionStatus.PENDING_PAYMENT.value,
                    )
                )
            ).one_or_none()
            if pair is None:
                raise PaymentError("خرید در انتظار پرداخت پیدا نشد.")
            return _instructions(pair[0], pair[1], pair[2] or "اشتراک")

    async def submit_receipt(self, telegram_id: int, order_id: str, image: bytes) -> str:
        cleaned = await sanitize_receipt(image)
        digest = hashlib.sha256(cleaned).hexdigest()
        ciphertext = await asyncio.to_thread(self._cipher.encrypt, cleaned)
        try:
            async with self._session_factory() as session, session.begin():
                order = await session.get(SubscriptionModel, order_id, with_for_update=True)
                if order is None or order.telegram_id != telegram_id:
                    raise PaymentError("خرید پیدا نشد.")
                await require_user_access(session, telegram_id)
                if order.status != SubscriptionStatus.PENDING_PAYMENT.value:
                    raise PaymentError("این خرید دیگر در انتظار رسید نیست.")
                if await session.get(CardPaymentOrderModel, order_id) is None:
                    raise PaymentError("ابتدا اطلاعات پرداخت این خرید را دریافت کن.")
                prior = await session.scalar(
                    select(PaymentReceiptModel).where(PaymentReceiptModel.image_digest == digest)
                )
                if prior:
                    if prior.order_id == order_id and prior.status == ReceiptStatus.PENDING.value:
                        return prior.id
                    raise PaymentError("این عکس رسید قبلاً ثبت شده است.")
                pending = await session.scalar(
                    select(PaymentReceiptModel.id).where(
                        PaymentReceiptModel.order_id == order_id,
                        PaymentReceiptModel.status == ReceiptStatus.PENDING.value,
                    )
                )
                if pending:
                    raise PaymentError("رسید این خرید در حال بررسی است؛ منتظر نتیجه بمان.")
                receipt = PaymentReceiptModel(
                    id=str(uuid4()),
                    order_id=order_id,
                    image_ciphertext=ciphertext,
                    image_digest=digest,
                    status=ReceiptStatus.PENDING.value,
                    created_at=_now(),
                )
                session.add(receipt)
                return receipt.id
        except IntegrityError as exc:
            raise PaymentError("این عکس رسید قبلاً ثبت شده است.") from exc

    async def receipt_status(self, telegram_id: int, order_id: str) -> ReceiptStatus | None:
        async with self._session_factory() as session:
            status = await session.scalar(
                select(PaymentReceiptModel.status)
                .join(SubscriptionModel, SubscriptionModel.id == PaymentReceiptModel.order_id)
                .where(
                    PaymentReceiptModel.order_id == order_id,
                    SubscriptionModel.telegram_id == telegram_id,
                )
                .order_by(PaymentReceiptModel.created_at.desc(), PaymentReceiptModel.id.desc())
                .limit(1)
            )
        return ReceiptStatus(status) if status else None

    async def receipts(self, *, offset: int = 0) -> list[PaymentReceipt]:
        statement = (
            select(
                PaymentReceiptModel.id,
                PaymentReceiptModel.order_id,
                SubscriptionModel.telegram_id,
                UserModel.display_name,
                PlanModel.title,
                SubscriptionModel.price_rial,
                PaymentReceiptModel.status,
                PaymentReceiptModel.created_at,
                PaymentReceiptModel.reviewed_at,
                PaymentReceiptModel.reviewed_by,
                PaymentReceiptModel.rejection_reason,
                ManualSettlementModel.bank_reference,
                CardPaymentOrderModel.card_number,
                CardPaymentOrderModel.bank_name,
                CardPaymentOrderModel.account_holder,
            )
            .join(SubscriptionModel, SubscriptionModel.id == PaymentReceiptModel.order_id)
            .join(UserModel, UserModel.telegram_id == SubscriptionModel.telegram_id)
            .join(CardPaymentOrderModel, CardPaymentOrderModel.order_id == SubscriptionModel.id)
            .outerjoin(PlanModel, PlanModel.code == SubscriptionModel.plan_code)
            .outerjoin(
                ManualSettlementModel, ManualSettlementModel.receipt_id == PaymentReceiptModel.id
            )
            .order_by(
                (PaymentReceiptModel.status == ReceiptStatus.PENDING.value).desc(),
                PaymentReceiptModel.created_at.desc(),
                PaymentReceiptModel.id.desc(),
            )
            .offset(max(0, offset))
            .limit(50)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).mappings().all()
        return [
            PaymentReceipt(
                r["id"],
                r["order_id"],
                r["telegram_id"],
                r["display_name"],
                r["title"] or "اشتراک",
                r["price_rial"],
                ReceiptStatus(r["status"]),
                r["created_at"].replace(tzinfo=UTC),
                r["reviewed_at"].replace(tzinfo=UTC) if r["reviewed_at"] else None,
                r["reviewed_by"],
                r["rejection_reason"],
                r["bank_reference"],
                r["card_number"],
                r["bank_name"],
                r["account_holder"],
            )
            for r in rows
        ]

    async def receipt_image(self, receipt_id: str) -> bytes:
        async with self._session_factory() as session:
            encrypted = await session.scalar(
                select(PaymentReceiptModel.image_ciphertext).where(
                    PaymentReceiptModel.id == receipt_id
                )
            )
        if encrypted is None:
            raise PaymentError("رسید پیدا نشد.")
        try:
            return await asyncio.to_thread(self._cipher.decrypt, encrypted)
        except InvalidToken as exc:
            raise PaymentError("عکس رسید در دسترس نیست.") from exc

    async def review(
        self, receipt_id: str, approved: bool, actor: str, bank_reference: str, reason: str
    ) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                order_id = await session.scalar(
                    select(PaymentReceiptModel.order_id).where(PaymentReceiptModel.id == receipt_id)
                )
                if order_id is None:
                    raise PaymentError("رسید پیدا نشد.")
                order = await session.get(SubscriptionModel, order_id, with_for_update=True)
                receipt = await session.get(PaymentReceiptModel, receipt_id, with_for_update=True)
                assert order is not None and receipt is not None
                if receipt.status == ReceiptStatus.APPROVED.value and approved:
                    settled = await session.get(ManualSettlementModel, order_id)
                    if settled and settled.bank_reference == bank_reference:
                        return
                    raise PaymentError("اطلاعات تأیید قبلی قابل تغییر نیست.")
                if (
                    receipt.status != ReceiptStatus.PENDING.value
                    or order.status != SubscriptionStatus.PENDING_PAYMENT.value
                ):
                    raise PaymentError("این رسید قبلاً بررسی شده است.")
                if approved:
                    await require_user_access(session, order.telegram_id)
                    duplicate = await session.scalar(
                        select(ManualSettlementModel.order_id).where(
                            ManualSettlementModel.bank_reference == bank_reference
                        )
                    )
                    if duplicate:
                        raise PaymentError("این تراکنش بانکی قبلاً برای خرید دیگری ثبت شده است.")
                    session.add(
                        ManualSettlementModel(
                            order_id=order.id,
                            receipt_id=receipt.id,
                            bank_reference=bank_reference,
                            amount_rial=order.price_rial,
                            approved_at=_now(),
                            approved_by=actor,
                        )
                    )
                    order.status = SubscriptionStatus.PAID_AWAITING_PROVISIONING.value
                receipt.status = (
                    ReceiptStatus.APPROVED.value if approved else ReceiptStatus.REJECTED.value
                )
                receipt.reviewed_at, receipt.reviewed_by = _now(), actor
                receipt.rejection_reason = "" if approved else reason
        except IntegrityError as exc:
            raise PaymentError("این تراکنش بانکی قبلاً ثبت شده است.") from exc

    async def claim_notifications(self) -> list[ReceiptNotification]:
        now = _now()
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.execute(
                    select(PaymentReceiptModel, SubscriptionModel.telegram_id)
                    .join(SubscriptionModel, SubscriptionModel.id == PaymentReceiptModel.order_id)
                    .where(
                        PaymentReceiptModel.status.in_(
                            [ReceiptStatus.APPROVED.value, ReceiptStatus.REJECTED.value]
                        ),
                        PaymentReceiptModel.notice_sent_at.is_(None),
                        or_(
                            PaymentReceiptModel.notice_leased_until.is_(None),
                            PaymentReceiptModel.notice_leased_until < now,
                        ),
                    )
                    .order_by(PaymentReceiptModel.reviewed_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            result = []
            for row, owner in rows:
                row.notice_leased_until = now + timedelta(minutes=2)
                result.append(
                    ReceiptNotification(
                        row.id, row.order_id, owner, ReceiptStatus(row.status), row.rejection_reason
                    )
                )
            return result

    async def finish_notification(self, receipt_id: str, *, sent: bool) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(PaymentReceiptModel, receipt_id, with_for_update=True)
            if row:
                if sent:
                    row.notice_sent_at = _now()
                row.notice_leased_until = None
