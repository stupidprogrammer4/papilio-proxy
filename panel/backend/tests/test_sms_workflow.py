import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

import httpx
import yaml
from alembic import command
from alembic.config import Config
from papilio.api.application import create_app
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import MySQLUnitOfWork

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.services import CustomerService
from src.modules.accounts.customers.domain.dtos import (
    CustomerAccessState,
    CustomerCreate,
)
from src.modules.accounts.customers.infra.mysql import CustomerRepository
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader
from src.modules.billing.destinations.app.services import (
    PaymentDestinationService,
)
from src.modules.billing.destinations.infra.mysql import (
    PaymentDestinationRepository,
)
from src.modules.billing.payment_identifiers.app.allocation import (
    PaymentAmountAllocationQuery,
)
from src.modules.billing.payment_identifiers.app.reservations import (
    PaymentAmountReservationService,
)
from src.modules.billing.payment_identifiers.infra.mysql import (
    PaymentAmountReservationRepository,
)
from src.modules.billing.payment_identifiers.infra.readers import (
    PaymentAmountReader,
)
from src.modules.billing.sms.app.parser import observe
from src.modules.billing.sms.infra.mysql import SmsRepository
from src.modules.billing.sms_origins.app.accounts import ReceivingAliasService
from src.modules.billing.sms_origins.app.manual_guard import (
    SmsManualPaymentGuard,
)
from src.modules.billing.sms_origins.app.services import (
    ReceivingRealmService,
    SmsOriginAdmissionService,
)
from src.modules.billing.sms_origins.infra.financial import SmsFinancialReader
from src.modules.billing.sms_origins.infra.mysql import (
    ReceivingAliasRepository,
    ReceivingRealmRepository,
    SmsOriginAdmissionRepository,
)
from src.modules.billing.wallet.app.commands import WalletCommand
from src.modules.billing.wallet.domain.dtos import TopupCreate
from src.modules.billing.wallet.infra.mysql import (
    TopupRepository,
    WalletRepository,
)
from src.modules.operations.notifications.app.commands import (
    NotificationCreateCommand,
)
from src.modules.operations.notifications.app.queries import (
    NotificationPolicyQuery,
)
from src.modules.operations.notifications.infra.mysql import (
    NotificationRepository,
)
from src.modules.operations.preferences.app.services import PreferencesService
from src.modules.operations.preferences.infra.mysql import (
    PreferencesRepository,
)

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


class SmsParsingTest(IsolatedAsyncioTestCase):
    async def test_credit_amount_and_debit_rejection(self) -> None:
        self.assertEqual(
            observe("واریز ۹۰٬۰۰۰ تومان، پیگیری: ۱۲۳۴۵۶"),
            (900_000, "123456"),
        )
        self.assertEqual(observe("برداشت ۹۰٬۰۰۰ تومان"), (None, None))


@skipUnless(TEST_URL, "Requires an isolated PAPILIO_TEST_DATABASE_URL")
class SmsWebhookTest(IsolatedAsyncioTestCase):
    async def test_signed_duplicate_is_stored_once(self) -> None:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", str(TEST_URL))
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, config, "head")
        with open("config.yml.sample", encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        raw["rate_limit"]["enabled"] = False
        raw["db"]["dsn"] = TEST_URL
        raw["db"]["test_dsn"] = TEST_URL
        settings = PapilioSettings.model_validate(raw)
        assert settings.db is not None
        connection = DBConnection(
            dsn=settings.db.dsn,
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        event_id = "phone_" + uuid4().hex
        username = "owner_" + uuid4().hex[:12]
        amount_toman = 100_000 + int(uuid4().hex[:6], 16)
        async with connection.uow() as unit:
            customer = await CustomerService(
                CustomerRepository(unit),
                settings,
                PreferencesService(PreferencesRepository(unit), settings),
            ).create(
                CustomerCreate(
                    display_name="خریدار",
                    access=CustomerAccessState(
                        is_active=True,
                        services_enabled=True,
                        renewals_enabled=True,
                    ),
                )
            )
            receiving_realms = ReceivingRealmService(
                ReceivingRealmRepository(unit), settings
            )
            sms_admission = SmsOriginAdmissionService(
                SmsOriginAdmissionRepository(unit)
            )
            sms_reader = SmsFinancialReader(unit)
            topup = await WalletCommand(
                CustomerRepository(unit),
                WalletRepository(unit),
                TopupRepository(unit),
                settings,
                PreferencesService(PreferencesRepository(unit), settings),
                PaymentDestinationService(
                    PaymentDestinationRepository(unit),
                    settings,
                    PreferencesService(PreferencesRepository(unit), settings),
                ),
                NotificationCreateCommand(
                    NotificationRepository(unit),
                    CustomerRepository(unit),
                    NotificationPolicyQuery(
                        PreferencesService(
                            PreferencesRepository(unit), settings
                        ),
                        settings,
                    ),
                ),
                SmsManualPaymentGuard(
                    sms_reader, sms_admission, receiving_realms
                ),
                ReceivingAliasService(
                    ReceivingAliasRepository(unit), settings
                ),
                receiving_realms,
                PaymentAmountAllocationQuery(
                    PaymentAmountReader(unit), settings
                ),
                PaymentAmountReservationService(
                    PaymentAmountReservationRepository(unit)
                ),
            ).request_topup(
                TopupCreate(
                    customer_id=customer.id,
                    amount_rial=amount_toman * 10,
                )
            )
            await StaffAuth(
                StaffRepository(unit),
                Passwords(settings),
                settings,
                StaffSessionReader(unit),
            ).create_owner(username, "local-only-password-123")
        app = create_app(
            settings,
            providers=infrastructure_providers(settings),
            middleware=(),
            docs_url=None,
        )
        try:
            body = json.dumps(
                {
                    "event_id": event_id,
                    "sender": "BANK",
                    "message": f"واریز {amount_toman:,} تومان، پیگیری ۱۲۳۴۵۶",
                    "sent_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
            ).encode()
            timestamp = str(int(time.time()))
            digest = hmac.new(
                settings.security.sms_webhook_key.encode(),
                timestamp.encode() + b"." + body,
                hashlib.sha256,
            ).hexdigest()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://admin.example.com",
            ) as client:
                denied = await client.post("/v1/webhooks/sms", content=body)
                self.assertEqual(denied.status_code, 401)
                headers = {
                    "X-Papilio-Timestamp": timestamp,
                    "X-Papilio-Signature": digest,
                    "Content-Type": "application/json",
                }
                first = await client.post(
                    "/v1/webhooks/sms", content=body, headers=headers
                )
                replay = await client.post(
                    "/v1/webhooks/sms", content=body, headers=headers
                )
                self.assertEqual(first.status_code, 200)
                self.assertEqual(replay.status_code, 200)
                changed_body = body.replace(
                    f"{amount_toman:,}".encode(),
                    f"{amount_toman + 1:,}".encode(),
                )
                changed_signature = hmac.new(
                    settings.security.sms_webhook_key.encode(),
                    timestamp.encode() + b"." + changed_body,
                    hashlib.sha256,
                ).hexdigest()
                changed = await client.post(
                    "/v1/webhooks/sms",
                    content=changed_body,
                    headers={
                        **headers,
                        "X-Papilio-Signature": changed_signature,
                    },
                )
                self.assertEqual(changed.status_code, 409)
                login = await client.post(
                    "/v1/admin/auth/login",
                    headers={"Origin": settings.public.admin_origin},
                    json={
                        "username": username,
                        "password": "local-only-password-123",
                    },
                )
                self.assertEqual(login.status_code, 200)
                candidates = await client.get(
                    f"/v1/admin/payments/sms/candidates/{topup.id}"
                )
                self.assertEqual(candidates.status_code, 200)
                self.assertIn(
                    event_id,
                    [row["event_id"] for row in candidates.json()["data"]],
                )
            async with connection.uow() as independent:
                observed = await SmsRepository(independent).by_event_id(
                    event_id
                )
                self.assertIsNotNone(observed)
                assert observed is not None
                self.assertEqual(observed.amount_rial, amount_toman * 10)
                self.assertEqual(observed.bank_reference, "123456")
        finally:
            await app.state.dishka_container.close()
            await connection.dispose()
