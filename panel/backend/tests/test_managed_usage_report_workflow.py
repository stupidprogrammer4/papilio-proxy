"""Ordinary reports with explicit persisted managed-storage fixtures."""

import asyncio
from datetime import UTC, datetime

from papilio.infra.db.transaction import transaction
from sqlalchemy import text

from tests.test_managed_installation_workflow import (
    ManagedInstallationWorkflowFixture,
)


class ManagedUsageReportWorkflowTest(ManagedInstallationWorkflowFixture):
    async def setup_grant(self):
        _, subscription, node, configuration = await self.setup_installation()
        async with self.connection.uow() as unit:
            result = await unit.execute(
                text(
                    "SELECT id FROM tbl_profiles WHERE subscription_id=:sid "
                    "AND configuration_id=:configuration"
                ),
                {
                    "sid": subscription["id"],
                    "configuration": configuration["id"],
                },
            )
            profile_id = result.scalar_one()
        response = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants",
            headers=self.node_headers,
            json={
                "profile_id": profile_id,
                "generation": 0,
                "request_key": "managed_report_" + self.suffix,
                "requested_bytes": 1024,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        grant = response.json()["data"]
        self.report_path = (
            f"/v1/nodes/{node['node']['code']}/usage/grants/"
            f"{grant['id']}/reports"
        )
        return subscription, node, configuration, grant

    async def link_managed_storage(
        self, subscription, node, configuration, grant
    ):
        # Constructed storage facts prove the report boundary, not admission.
        async with self.connection.uow() as unit:
            async with transaction(unit):
                await unit.execute(
                    text(
                        "INSERT INTO tbl_managed_installations "
                        "(node_id,core_id,runtime_revision_id,installation_sha256,"
                        "encrypted_manifest,state) VALUES "
                        "(:node,:core,:revision,:digest,'fixture','installed_closed')"
                    ),
                    {
                        "node": node["node"]["id"],
                        "core": configuration["core_id"],
                        "revision": self.issue_data["runtime_revision_id"],
                        "digest": "a" * 64,
                    },
                )
                installation = await unit.execute(
                    text(
                        "SELECT id FROM tbl_managed_installations WHERE "
                        "core_id=:core AND runtime_revision_id=:revision "
                        "AND installation_sha256=:digest"
                    ),
                    {
                        "core": configuration["core_id"],
                        "revision": self.issue_data["runtime_revision_id"],
                        "digest": "a" * 64,
                    },
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_managed_epoches "
                        "(installation_id,process_epoch,installed_closed_at,"
                        "receipt_sha256,encrypted_receipt) VALUES "
                        "(:installation,:epoch,:at,:digest,'fixture')"
                    ),
                    {
                        "installation": installation.scalar_one(),
                        "epoch": "b" * 32,
                        "at": datetime.now(UTC).replace(tzinfo=None),
                        "digest": "c" * 64,
                    },
                )
                epoch = await unit.execute(
                    text(
                        "SELECT id FROM tbl_managed_epoches "
                        "WHERE process_epoch=:epoch"
                    ),
                    {"epoch": "b" * 32},
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_managed_windows "
                        "(epoch_id,grant_id,profile_id,subscription_id,generation,"
                        "window_id,request_key,request_sha256,window_sha256,"
                        "baseline_upload_bytes,baseline_download_bytes,allocated_bytes,"
                        "issued_at,valid_until,encrypted_window) VALUES "
                        "(:epoch,:grant,:profile,:sid,0,:window,:request,:digest,"
                        ":digest,0,0,1024,:at,:until,'fixture')"
                    ),
                    {
                        "epoch": epoch.scalar_one(),
                        "grant": grant["id"],
                        "profile": grant["profile_id"],
                        "sid": subscription["id"],
                        "window": "d" * 32,
                        "request": "managed_report_" + self.suffix,
                        "digest": "e" * 64,
                        "at": datetime.now(UTC).replace(tzinfo=None),
                        "until": datetime.fromisoformat(
                            grant["valid_until"]
                        ).replace(tzinfo=None),
                    },
                )

    def report_body(self, final):
        return {
            "event_id": "managed_boundary_" + self.suffix,
            "sequence": 1,
            "upload_bytes": 120,
            "download_bytes": 30,
            "sampled_at": datetime.now(UTC).isoformat(),
            "final": final,
        }

    async def assert_accounting(self, subscription, grant, expected):
        async with self.connection.uow() as fresh:
            row = await fresh.execute(
                text(
                    "SELECT upload_bytes,download_bytes,sequence,is_closed "
                    "FROM tbl_usage_grants WHERE id=:id"
                ),
                {"id": grant["id"]},
            )
            self.assertEqual(tuple(row.one()), expected[:4])
            events = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_usage_events WHERE grant_id=:id"
                ),
                {"id": grant["id"]},
            )
            self.assertEqual(events.scalar_one(), expected[4])
            usage = await fresh.execute(
                text("SELECT used_bytes FROM tbl_subscriptions WHERE id=:id"),
                {"id": subscription["id"]},
            )
            self.assertEqual(usage.scalar_one(), expected[5])

    async def test_managed_storage_blocks_reports_when_disabled(
        self,
    ):
        subscription, node, configuration, grant = await self.setup_grant()
        await self.link_managed_storage(
            subscription, node, configuration, grant
        )
        self.settings.managed_adapter = None
        responses = await asyncio.gather(
            self.client.post(
                self.report_path,
                headers=self.node_headers,
                json=self.report_body(False),
            ),
            self.client.post(
                self.report_path,
                headers=self.node_headers,
                json=self.report_body(True),
            ),
        )
        self.assertEqual([row.status_code for row in responses], [409, 409])
        await self.assert_accounting(
            subscription, grant, (0, 0, 0, False, 0, 0)
        )

    async def test_ordinary_replay_then_managed_link_blocks_replay(
        self,
    ):
        subscription, node, configuration, grant = await self.setup_grant()
        body = self.report_body(True)
        accepted = await self.client.post(
            self.report_path, headers=self.node_headers, json=body
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        replay = await self.client.post(
            self.report_path, headers=self.node_headers, json=body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            replay.json()["data"]["id"], accepted.json()["data"]["id"]
        )
        await self.assert_accounting(
            subscription, grant, (120, 30, 1, True, 1, 150)
        )
        await self.link_managed_storage(
            subscription, node, configuration, grant
        )
        replay = await self.client.post(
            self.report_path, headers=self.node_headers, json=body
        )
        self.assertEqual(replay.status_code, 409, replay.text)
        await self.assert_accounting(
            subscription, grant, (120, 30, 1, True, 1, 150)
        )
