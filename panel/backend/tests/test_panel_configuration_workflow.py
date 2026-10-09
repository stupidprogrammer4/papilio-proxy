import asyncio
import os
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class PanelConfigurationWorkflowTest(
    StaffAdministrationWorkflowTest, FulfillmentWorkflowFixture
):
    async def test_sms_upgrade_downgrade_preserves_existing_purchase(self):
        subscription, _, _, _ = await self.setup_sale()
        migration = Config("alembic.ini")
        migration.set_main_option(
            "sqlalchemy.url",
            self.connection.engine.url.render_as_string(hide_password=False),
        )
        async with self.connection.uow() as fresh:
            before = (
                await fresh.execute(
                    text(
                        "SELECT balance_rial FROM tbl_wallets "
                        "WHERE customer_id=:id"
                    ),
                    {"id": subscription["customer_id"]},
                )
            ).scalar_one()
        with patch.dict(os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}):
            await asyncio.to_thread(
                command.downgrade,
                migration,
                "0039_configuration_json_payloads",
            )
            await asyncio.to_thread(command.upgrade, migration, "head")
        async with self.connection.uow() as fresh:
            after = (
                await fresh.execute(
                    text(
                        "SELECT balance_rial FROM tbl_wallets "
                        "WHERE customer_id=:id"
                    ),
                    {"id": subscription["customer_id"]},
                )
            ).scalar_one()
        self.assertEqual(after, before)
        self.assertEqual(
            (await self.get(f"/v1/admin/subscriptions/{subscription['id']}"))[
                "data"
            ]["id"],
            subscription["id"],
        )

    async def test_plan_bundle_and_customer_configuration_context(self):
        subscription, request, nodes, purchase = await self.setup_sale()
        plan_id = purchase["plan_id"]
        public_path = f"/v1/plans/{plan_id}/configurations"
        admin_path = f"/v1/admin/plans/{plan_id}/configurations"
        first = await self.get(public_path + "?per_page=1")
        second = await self.get(public_path + "?per_page=1&page=2")
        self.assertEqual(first["meta"]["pager"]["total_items"], 2)
        options = first["data"] + second["data"]
        self.assertEqual(len({row["configuration_id"] for row in options}), 2)
        self.assertEqual(
            {row["node_id"] for row in options},
            {row["node"]["id"] for row in nodes},
        )
        self.assertTrue(all(row["node_label"] for row in options))
        self.assertTrue(all(row["is_enabled"] for row in options))
        self.assertTrue(
            all(
                "settings_json" not in row and "credential" not in row
                for row in options
            )
        )

        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        customer_id = subscription["customer_id"]
        customer_path = f"/v1/admin/customers/{customer_id}/configurations"
        assigned_first = await self.get(customer_path + "?per_page=1")
        assigned_second = await self.get(customer_path + "?per_page=1&page=2")
        self.assertEqual(assigned_first["meta"]["pager"]["total_items"], 2)
        assigned = assigned_first["data"] + assigned_second["data"]
        self.assertEqual(len({row["profile_id"] for row in assigned}), 2)
        self.assertEqual(
            {row["configuration_id"] for row in assigned},
            {row["configuration_id"] for row in options},
        )
        self.assertTrue(
            all(
                row["customer_id"] == customer_id
                and row["subscription_id"] == subscription["id"]
                and row["plan_id"] == plan_id
                and row["plan_title"]
                and row["configuration_label"]
                and row["node_label"]
                for row in assigned
            )
        )
        other = await self.post(
            "/v1/admin/customers", {"display_name": "Other customer"}
        )
        other_path = f"/v1/admin/customers/{other['id']}/configurations"
        other_rows = await self.get(
            other_path + f"?subscription_id={subscription['id']}"
        )
        self.assertEqual(other_rows["data"], [])
        self.assertEqual(other_rows["meta"]["pager"]["total_items"], 0)

        disabled_id = nodes[0]["node"]["id"]
        disabled = await self.client.patch(
            f"/v1/admin/network/nodes/{disabled_id}/enabled",
            headers=self.headers,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        public = await self.get(public_path + "?per_page=1")
        admin = await self.get(admin_path)
        self.assertEqual(public["meta"]["pager"]["total_items"], 1)
        self.assertTrue(
            all(row["node_id"] != disabled_id for row in public["data"])
        )
        self.assertEqual(admin["meta"]["pager"]["total_items"], 2)
        self.assertTrue(
            all(
                row["is_enabled"] == (row["node_id"] != disabled_id)
                for row in admin["data"]
            )
        )
