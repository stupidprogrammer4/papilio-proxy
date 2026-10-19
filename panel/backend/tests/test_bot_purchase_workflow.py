import asyncio
import os
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
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.config.providers import infrastructure_providers
from src.config.settings import PapilioSettings
from src.modules.accounts.staff.app.passwords import Passwords
from src.modules.accounts.staff.app.services import StaffAuth
from src.modules.accounts.staff.infra.mysql import StaffRepository
from src.modules.accounts.staff.infra.readers import StaffSessionReader
from src.modules.billing.destinations.app.services import (
    PaymentDestinationService,
)
from src.modules.billing.destinations.domain.dtos import DestinationWrite
from src.modules.billing.destinations.infra.mysql import (
    PaymentDestinationRepository,
)
from src.modules.billing.wallet.domain.dtos import TopupApproval
from src.modules.billing.wallet.infra.mysql import (
    WalletRepository,
)
from src.modules.billing.wallet.interfaces import IWalletCommand
from src.modules.network.routing.app.services import HostGroupService
from src.modules.network.routing.infra.mysql import HostGroupRepository
from src.modules.operations.preferences.app.services import PreferencesService
from src.modules.operations.preferences.domain.dtos import PreferencesWrite
from src.modules.operations.preferences.infra.mysql import (
    PreferencesRepository,
)
from src.modules.sales.catalog.app.services import PlanService
from src.modules.sales.catalog.domain.dtos import PlanCreate, PlanSetActive
from src.modules.sales.catalog.infra.mysql import PlanRepository

TEST_URL = os.getenv("PAPILIO_TEST_DATABASE_URL")


@skipUnless(TEST_URL, "Requires an isolated PAPILIO_TEST_DATABASE_URL")
class BotPurchaseWorkflowTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "papilio_upgrade_test_bot_" + uuid4().hex[:12]
        self.maintenance = DBConnection(
            dsn=str(TEST_URL),
            pool_size=1,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{self.schema}`"))
        self.test_url = (
            make_url(str(TEST_URL))
            .set(database=self.schema)
            .render_as_string(hide_password=False)
        )

    async def asyncTearDown(self):
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"DROP DATABASE `{self.schema}`"))
        await self.maintenance.dispose()

    async def test_bot_key_wallet_purchase_and_subscription_ownership(
        self,
    ) -> None:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", self.test_url)
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(command.upgrade, config, "head")
        with open("config.yml.sample", encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        raw["rate_limit"]["enabled"] = False
        raw["db"]["dsn"] = self.test_url
        raw["db"]["test_dsn"] = self.test_url
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
        username = "owner_" + uuid4().hex[:12]
        telegram_id = int(uuid4().hex[:12], 16)
        other_telegram_id = int(uuid4().hex[:12], 16)
        async with connection.uow() as unit:
            staff = StaffAuth(
                StaffRepository(unit),
                Passwords(settings),
                settings,
                StaffSessionReader(unit),
            )
            await staff.create_owner(username, "local-only-password-123")
        async with connection.uow() as unit:
            owner = await StaffRepository(unit).by_username(username)
            assert owner is not None
            owner_id = owner.id
            plans = PlanService(
                PlanRepository(unit),
                settings,
                HostGroupService(HostGroupRepository(unit), settings),
                PreferencesService(PreferencesRepository(unit), settings),
            )
            plan = await plans.create(
                PlanCreate(
                    code="bot_" + uuid4().hex[:10],
                    title="پلن بات",
                    quota_bytes=1_073_741_824,
                    duration_days=30,
                    price_rial=100_000,
                )
            )
            await plans.set_active(plan.id, PlanSetActive(is_active=True))
        async with connection.uow() as unit:
            destinations = PaymentDestinationService(
                PaymentDestinationRepository(unit),
                settings,
                PreferencesService(PreferencesRepository(unit), settings),
            )
            destination = await destinations.create(
                DestinationWrite(
                    title="Controlled bank",
                    kind="card",
                    account="1111222233334444",
                    recipient="Test",
                    bank_name="Test bank",
                    is_active=True,
                )
            )
        app = create_app(
            settings,
            providers=infrastructure_providers(settings),
            middleware=(),
            docs_url=None,
        )
        try:
            async with connection.uow() as unit:
                preferences = PreferencesService(
                    PreferencesRepository(unit), settings
                )
                current = await preferences.current()
                current.values.bot_presentation.localized_texts[
                    "fa"
                ].welcome_message = "پیکربندی تست {display_name}"
                current.values.bot_presentation.welcome_photo_url = (
                    "https://cdn.example.test/panel-bot.webp"
                )
                current.values.bot_presentation.show_trials = False
                await preferences.write(
                    PreferencesWrite(
                        expected_revision=current.revision,
                        values=current.values,
                    ),
                    owner_id,
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                identity = {
                    "telegram_id": telegram_id,
                    "display_name": "کاربر بات",
                }
                unauthorized = await client.post("/v1/bot/home", json=identity)
                self.assertEqual(unauthorized.status_code, 401)
                headers = {
                    "X-Papilio-Bot-Key": settings.security.bot_service_key
                }
                home = await client.post(
                    "/v1/bot/home", json=identity, headers=headers
                )
                self.assertEqual(home.status_code, 200)
                presentation = home.json()["data"]["presentation"]
                self.assertEqual(
                    presentation["welcome_message"],
                    "پیکربندی تست {display_name}",
                )
                self.assertEqual(
                    presentation["welcome_photo_url"],
                    "https://cdn.example.test/panel-bot.webp",
                )
                self.assertEqual(
                    presentation["message_catalog"]["درخواست انجام نشد."],
                    "درخواست انجام نشد.",
                )
                self.assertFalse(
                    next(
                        button
                        for button in presentation["menu_buttons"]
                        if button["action"] == "trial"
                    )["visible"]
                )
                unauthorized_presentation = await client.get(
                    "/v1/bot/presentation"
                )
                self.assertEqual(unauthorized_presentation.status_code, 401)
                latest_presentation = await client.get(
                    "/v1/bot/presentation?locale=fa", headers=headers
                )
                self.assertEqual(latest_presentation.status_code, 200)
                self.assertFalse(
                    next(
                        button
                        for button in latest_presentation.json()["data"][
                            "menu_buttons"
                        ]
                        if button["action"] == "trial"
                    )["visible"]
                )
                async with connection.uow() as unit:
                    preferences = PreferencesService(
                        PreferencesRepository(unit), settings
                    )
                    current = await preferences.current()
                    current.values.bot_presentation.show_trials = True
                    await preferences.write(
                        PreferencesWrite(
                            expected_revision=current.revision,
                            values=current.values,
                        ),
                        owner_id,
                    )
                latest_presentation = await client.get(
                    "/v1/bot/presentation?locale=en", headers=headers
                )
                self.assertTrue(
                    next(
                        button
                        for button in latest_presentation.json()["data"][
                            "menu_buttons"
                        ]
                        if button["action"] == "trial"
                    )["visible"]
                )
                self.assertTrue(
                    latest_presentation.json()["data"][
                        "welcome_message"
                    ].startswith("Hello ")
                )
                locale_error_messages = {
                    "en": "Request failed.",
                    "ru": "Не удалось выполнить запрос.",
                    "zh": "请求未能完成。",
                }
                localized_responses = await asyncio.gather(
                    *(
                        client.get(
                            f"/v1/bot/presentation?locale={locale}",
                            headers=headers,
                        )
                        for locale in locale_error_messages
                    )
                )
                for expected_error, localized in zip(
                    locale_error_messages.values(),
                    localized_responses,
                    strict=True,
                ):
                    self.assertEqual(localized.status_code, 200)
                    localized_data = localized.json()["data"]
                    self.assertEqual(
                        localized_data["message_catalog"][
                            "درخواست انجام نشد."
                        ],
                        expected_error,
                    )
                    self.assertTrue(
                        all(localized_data["message_catalog"].values())
                    )
                customer_id = home.json()["data"]["customer_id"]
                request_topup = await client.post(
                    "/v1/bot/topups",
                    json={
                        **identity,
                        "amount_rial": 200_000,
                        "destination_id": destination.destination_id,
                    },
                    headers=headers,
                )
                self.assertEqual(request_topup.status_code, 200)
                topup_id = request_topup.json()["data"]["id"]
                instruction_path = (
                    f"/v1/bot/topups/{topup_id}/payment-instruction"
                )
                unauthenticated = await client.post(
                    instruction_path, json=identity
                )
                self.assertEqual(unauthenticated.status_code, 401)
                captured = await client.post(
                    instruction_path, json=identity, headers=headers
                )
                self.assertEqual(captured.status_code, 200)
                self.assertEqual(
                    captured.json()["data"]["account"], "1111222233334444"
                )
                self.assertEqual(
                    captured.json()["data"]["payable_amount_rial"], 200_000
                )
                other_instruction = await client.post(
                    instruction_path,
                    json={
                        "telegram_id": other_telegram_id,
                        "display_name": "Other",
                    },
                    headers=headers,
                )
                self.assertEqual(other_instruction.status_code, 404)
                async with app.state.dishka_container() as scope:
                    billing = await scope.get(IWalletCommand)
                    await billing.approve(
                        topup_id,
                        TopupApproval(
                            expected_revision=1,
                            bank_reference="bank_" + uuid4().hex,
                        ),
                        owner_id,
                    )
                payload = {
                    **identity,
                    "plan_id": plan.id,
                    "auto_renew": True,
                    "purchase_key": "bot:" + uuid4().hex,
                }
                purchase = await client.post(
                    "/v1/bot/purchase",
                    json=payload,
                    headers=headers,
                )
                self.assertEqual(purchase.status_code, 200)
                subscription_id = purchase.json()["data"]["id"]
                replay = await client.post(
                    "/v1/bot/purchase", json=payload, headers=headers
                )
                self.assertEqual(replay.status_code, 200)
                self.assertEqual(replay.json()["data"]["id"], subscription_id)
                self.assertEqual(
                    purchase.json()["data"]["status"], "pending_provision"
                )
                home = await client.post(
                    "/v1/bot/home", json=identity, headers=headers
                )
                self.assertEqual(home.json()["data"]["balance_rial"], 100_000)
                other = await client.patch(
                    f"/v1/bot/subscriptions/{subscription_id}/auto-renew",
                    json={
                        "telegram_id": other_telegram_id,
                        "display_name": "کاربر دیگر",
                        "enabled": False,
                    },
                    headers=headers,
                )
                self.assertEqual(other.status_code, 404)
                mine = await client.post(
                    "/v1/bot/subscriptions/search",
                    json=identity,
                    headers=headers,
                )
                self.assertIn(
                    subscription_id, {row["id"] for row in mine.json()["data"]}
                )
                async with connection.uow() as independent:
                    wallet = await WalletRepository(independent).by_customer(
                        customer_id
                    )
                    assert wallet is not None
                    self.assertEqual(wallet.balance_rial, 100_000)
        finally:
            await app.state.dishka_container.close()
            await connection.dispose()
