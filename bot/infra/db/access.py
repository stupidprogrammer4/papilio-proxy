from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.models import (
    Base,
    PlanModel,
    PlanVisualModel,
    ProvisionDeliveryModel,
    SubscriptionAccessModel,
    SubscriptionModel,
    SubscriptionTermsModel,
    UsageAlertModel,
)
from bot.infra.db.pool import create_mysql_engine
from bot.infra.db.user_access import require_user_access, subscription_user_is_allowed
from bot.models.access import ProvisionDelivery, SubscriptionAccess, UsageAlert
from bot.models.node import ActiveNodeAccess, NodeAccount, PendingProvision
from bot.models.subscriptions import SubscriptionStatus
from bot.services.access import AccessUnavailable


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


class MysqlAccessRepository:
    """MySQL-only link vault, cumulative usage, and durable alert outbox."""

    def __init__(self, database_url: str, encryption_key: str) -> None:
        try:
            self._cipher = Fernet(encryption_key.encode())
        except ValueError as exc:
            raise AccessUnavailable("Invalid subscription encryption key") from exc
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    def _encrypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        try:
            return self._cipher.decrypt(value.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise AccessUnavailable("Subscription secret cannot be decrypted") from exc

    def _access(
        self, row: SubscriptionAccessModel, order: SubscriptionModel,
        title: str | None = None, emoji: str | None = None,
    ) -> SubscriptionAccess:
        if order.expires_at is None:
            raise AccessUnavailable("Active subscription has no expiry")
        return SubscriptionAccess(
            subscription_id=order.id,
            telegram_id=order.telegram_id,
            token=self._decrypt(row.token_ciphertext),
            vless_link=self._decrypt(row.vless_ciphertext),
            vmess_link=self._decrypt(row.vmess_ciphertext),
            traffic_limit_bytes=order.traffic_limit_bytes,
            uplink_bytes=row.uplink_bytes,
            downlink_bytes=row.downlink_bytes,
            expires_at=order.expires_at.replace(tzinfo=UTC),
            last_measured_at=row.last_measured_at.replace(tzinfo=UTC),
            status=SubscriptionStatus(order.status),
            plan_title=title or ("تست خصوصی" if order.price_rial == 0 else order.plan_code),
            plan_emoji=emoji or "🦋",
        )

    async def activate(
        self, subscription_id: str, token: str, vless_link: str,
        vmess_link: str, measured_at: datetime,
    ) -> SubscriptionAccess:
        async with self._session_factory() as session, session.begin():
            owner = await session.scalar(select(SubscriptionModel.telegram_id).where(
                SubscriptionModel.id == subscription_id,
            ))
            if owner is None:
                raise AccessUnavailable("Order does not exist")
            await require_user_access(session, owner)
            order = await session.scalar(
                select(SubscriptionModel)
                .where(SubscriptionModel.id == subscription_id)
                .with_for_update()
            )
            if order is None:
                raise AccessUnavailable("Order does not exist")
            existing = await session.get(SubscriptionAccessModel, subscription_id)
            if existing is not None:
                if (
                    order.status != SubscriptionStatus.ACTIVE.value
                    or self._decrypt(existing.vless_ciphertext) != vless_link
                    or self._decrypt(existing.vmess_ciphertext) != vmess_link
                ):
                    raise AccessUnavailable("Provisioning retry does not match existing access")
                return self._access(existing, order)
            terms = await session.get(SubscriptionTermsModel, subscription_id)
            if (
                order.status not in {
                    SubscriptionStatus.PAID_AWAITING_PROVISIONING.value,
                    SubscriptionStatus.TEST_AWAITING_PROVISIONING.value,
                }
                or terms is None or terms.duration_days <= 0
            ):
                raise AccessUnavailable("Order is unpaid or has no purchased duration snapshot")
            row = SubscriptionAccessModel(
                subscription_id=subscription_id,
                token_digest=sha256(token.encode()).hexdigest(),
                token_ciphertext=self._encrypt(token),
                vless_ciphertext=self._encrypt(vless_link),
                vmess_ciphertext=self._encrypt(vmess_link),
                uplink_bytes=0,
                downlink_bytes=0,
                last_measured_at=_naive(measured_at),
            )
            session.add(row)
            session.add(ProvisionDeliveryModel(subscription_id=subscription_id))
            order.status = SubscriptionStatus.ACTIVE.value
            order.expires_at = _naive(measured_at + timedelta(days=terms.duration_days))
            await session.flush()
            return self._access(row, order)

    async def get_by_token(self, token: str) -> SubscriptionAccess | None:
        digest = sha256(token.encode()).hexdigest()
        statement = (
            select(SubscriptionAccessModel, SubscriptionModel, PlanModel.title, PlanVisualModel.emoji)
            .join(SubscriptionModel, SubscriptionAccessModel.subscription_id == SubscriptionModel.id)
            .outerjoin(PlanModel, PlanModel.code == SubscriptionModel.plan_code)
            .outerjoin(PlanVisualModel, PlanVisualModel.plan_code == PlanModel.code)
            .where(
                SubscriptionAccessModel.token_digest == digest,
                subscription_user_is_allowed(),
            )
        )
        async with self._session_factory() as session:
            pair = (await session.execute(statement)).one_or_none()
        if pair is None:
            return None
        row, order, title, emoji = pair
        return self._access(row, order, title, emoji)

    async def get_for_user(
        self, telegram_id: int, subscription_id: str
    ) -> SubscriptionAccess | None:
        statement = (
            select(SubscriptionAccessModel, SubscriptionModel, PlanModel.title, PlanVisualModel.emoji)
            .join(SubscriptionModel, SubscriptionAccessModel.subscription_id == SubscriptionModel.id)
            .outerjoin(PlanModel, PlanModel.code == SubscriptionModel.plan_code)
            .outerjoin(PlanVisualModel, PlanVisualModel.plan_code == PlanModel.code)
            .where(
                SubscriptionAccessModel.subscription_id == subscription_id,
                SubscriptionModel.telegram_id == telegram_id,
                SubscriptionModel.status == SubscriptionStatus.ACTIVE.value,
                subscription_user_is_allowed(),
            )
        )
        async with self._session_factory() as session:
            pair = (await session.execute(statement)).one_or_none()
        if pair is None:
            return None
        row, order, title, emoji = pair
        return self._access(row, order, title, emoji)

    async def record_usage(
        self, subscription_id: str, uplink_bytes: int,
        downlink_bytes: int, measured_at: datetime,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(SubscriptionAccessModel)
                .where(SubscriptionAccessModel.subscription_id == subscription_id)
                .with_for_update()
            )
            order = await session.scalar(
                select(SubscriptionModel)
                .where(SubscriptionModel.id == subscription_id)
                .with_for_update()
            )
            if row is None or order is None or order.status != SubscriptionStatus.ACTIVE.value:
                raise AccessUnavailable("No active provisioned entitlement")
            if (
                _naive(measured_at) <= row.last_measured_at
                or uplink_bytes < row.uplink_bytes
                or downlink_bytes < row.downlink_bytes
                or uplink_bytes + downlink_bytes > 2**63 - 1
            ):
                raise AccessUnavailable("Usage must be fresh and cumulative")
            row.uplink_bytes = uplink_bytes
            row.downlink_bytes = downlink_bytes
            row.last_measured_at = _naive(measured_at)
            total = uplink_bytes + downlink_bytes
            order.traffic_used_bytes = total
            if total >= order.traffic_limit_bytes:
                order.status = SubscriptionStatus.EXPIRED.value
            if total * 5 >= order.traffic_limit_bytes * 4 and total < order.traffic_limit_bytes:
                existing = await session.scalar(
                    select(UsageAlertModel.id).where(
                        UsageAlertModel.subscription_id == subscription_id,
                        UsageAlertModel.kind == "quota_80",
                    )
                )
                if existing is None:
                    session.add(UsageAlertModel(subscription_id=subscription_id, kind="quota_80"))
            return total >= order.traffic_limit_bytes

    async def list_pending_paid(self, limit: int = 20) -> list[PendingProvision]:
        statement = (
            select(SubscriptionModel, SubscriptionTermsModel, PlanModel.title)
            .join(SubscriptionTermsModel, SubscriptionTermsModel.subscription_id == SubscriptionModel.id)
            .outerjoin(PlanModel, PlanModel.code == SubscriptionModel.plan_code)
            .where(SubscriptionModel.status.in_((
                SubscriptionStatus.PAID_AWAITING_PROVISIONING.value,
                SubscriptionStatus.TEST_AWAITING_PROVISIONING.value,
            )))
            .where(subscription_user_is_allowed())
            .order_by(SubscriptionModel.created_at)
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [
            PendingProvision(
                order.id, order.telegram_id, title or ("تست خصوصی" if order.price_rial == 0 else order.plan_code),
                order.traffic_limit_bytes, terms.duration_days,
            )
            for order, terms, title in rows
        ]

    async def list_active_node_access(self) -> list[ActiveNodeAccess]:
        # This runs every two seconds: never load or decrypt subscription secrets here.
        statement = (
            select(
                SubscriptionAccessModel.subscription_id,
                SubscriptionAccessModel.uplink_bytes,
                SubscriptionAccessModel.downlink_bytes,
                SubscriptionAccessModel.last_measured_at,
                SubscriptionModel.traffic_limit_bytes,
                SubscriptionModel.expires_at,
                SubscriptionModel.plan_code,
                PlanModel.title,
            )
            .join(SubscriptionModel, SubscriptionAccessModel.subscription_id == SubscriptionModel.id)
            .outerjoin(PlanModel, PlanModel.code == SubscriptionModel.plan_code)
            .where(
                SubscriptionModel.status == SubscriptionStatus.ACTIVE.value,
                subscription_user_is_allowed(),
            )
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        result: list[ActiveNodeAccess] = []
        for subscription_id, up, down, measured_at, limit, expires_at, code, title in rows:
            if expires_at is None:
                raise AccessUnavailable("Active subscription has no expiry")
            result.append(ActiveNodeAccess(
                NodeAccount(
                    str(subscription_id), int(limit), int(up), int(down),
                    expires_at.replace(tzinfo=UTC),
                    measured_at.replace(tzinfo=UTC) if measured_at is not None else None,
                ),
                str(title or code),
            ))
        return result

    async def mark_expired(self, subscription_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            order = await session.scalar(
                select(SubscriptionModel)
                .where(SubscriptionModel.id == subscription_id)
                .with_for_update()
            )
            if order is not None and order.status == SubscriptionStatus.ACTIVE.value:
                order.status = SubscriptionStatus.EXPIRED.value

    async def claim_deliveries(self, limit: int = 10) -> list[ProvisionDelivery]:
        now = datetime.now(UTC).replace(tzinfo=None)
        statement = (
            select(ProvisionDeliveryModel, SubscriptionAccessModel, SubscriptionModel)
            .join(SubscriptionAccessModel, ProvisionDeliveryModel.subscription_id == SubscriptionAccessModel.subscription_id)
            .join(SubscriptionModel, ProvisionDeliveryModel.subscription_id == SubscriptionModel.id)
            .where(
                ProvisionDeliveryModel.sent_at.is_(None),
                or_(
                    ProvisionDeliveryModel.leased_until.is_(None),
                    ProvisionDeliveryModel.leased_until < now,
                ),
                SubscriptionModel.status == SubscriptionStatus.ACTIVE.value,
                subscription_user_is_allowed(),
            )
            .order_by(SubscriptionModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._session_factory() as session, session.begin():
            rows = (await session.execute(statement)).all()
            result: list[ProvisionDelivery] = []
            for delivery, access, order in rows:
                delivery.leased_until = now + timedelta(minutes=2)
                result.append(ProvisionDelivery(order.id, self._access(access, order)))
            return result

    async def mark_delivery_sent(self, subscription_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(ProvisionDeliveryModel, subscription_id)
            if row is not None and row.sent_at is None:
                row.sent_at = datetime.now(UTC).replace(tzinfo=None)
                row.leased_until = None

    async def release_delivery(self, subscription_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(ProvisionDeliveryModel, subscription_id)
            if row is not None and row.sent_at is None:
                row.leased_until = None

    async def claim_alerts(self, limit: int = 20) -> list[UsageAlert]:
        now = datetime.now(UTC).replace(tzinfo=None)
        statement = (
            select(UsageAlertModel, SubscriptionModel)
            .join(SubscriptionModel, UsageAlertModel.subscription_id == SubscriptionModel.id)
            .where(
                UsageAlertModel.sent_at.is_(None),
                or_(UsageAlertModel.leased_until.is_(None), UsageAlertModel.leased_until < now),
                SubscriptionModel.status == SubscriptionStatus.ACTIVE.value,
                subscription_user_is_allowed(),
                SubscriptionModel.traffic_used_bytes < SubscriptionModel.traffic_limit_bytes,
            )
            .order_by(UsageAlertModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._session_factory() as session, session.begin():
            pairs = (await session.execute(statement)).all()
            alerts: list[UsageAlert] = []
            for alert, order in pairs:
                alert.leased_until = now + timedelta(minutes=2)
                alerts.append(
                    UsageAlert(
                        alert.id, order.id, order.telegram_id,
                        order.traffic_used_bytes, order.traffic_limit_bytes,
                    )
                )
            return alerts

    async def mark_alert_sent(self, alert_id: int) -> None:
        async with self._session_factory() as session, session.begin():
            alert = await session.get(UsageAlertModel, alert_id)
            if alert is not None and alert.sent_at is None:
                alert.sent_at = datetime.now(UTC).replace(tzinfo=None)
                alert.leased_until = None

    async def release_alert(self, alert_id: int) -> None:
        async with self._session_factory() as session, session.begin():
            alert = await session.get(UsageAlertModel, alert_id)
            if alert is not None and alert.sent_at is None:
                alert.leased_until = None
