"""Native MySQL seal acceptance with constructed component receipts."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from src.modules.network.managed_runtime.domain.epoch_seals import (
    ManagedEpochSealLimits,
    ManagedEpochSealPolicy,
)
from tests import test_managed_successors_workflow as successor_reporter


class ManagedEpochSealWorkflowFixture(
    successor_reporter.ManagedSuccessorWorkflowFixture
):
    def enable_seals(self):
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={
                "epoch_seal_policy": ManagedEpochSealPolicy(
                    mode="strict",
                    limits=ManagedEpochSealLimits.model_validate(
                        {
                            "max_windows_per_epoch": 8,
                            "max_receipt_bytes": 65536,
                            "max_epochs": 2,
                        }
                    ),
                )
            }
        )

    async def startup_sha(self, epoch):
        async with self.connection.uow() as fresh:
            result = await fresh.execute(
                text(
                    "SELECT receipt_sha256 FROM tbl_managed_epoches "
                    "WHERE process_epoch=:epoch"
                ),
                {"epoch": epoch},
            )
            return result.scalar_one()

    async def seal_count(self):
        async with self.connection.uow() as fresh:
            result = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_managed_epoch_seals")
            )
            return result.scalar_one()

    @staticmethod
    def submission(expected, startup_sha, epoch, issued=None, final_body=None):
        members = [
            {
                "binding": row["binding"],
                "membership_sha256": row["membership_sha256"],
                "profile_sha256": row["profile_sha256"],
            }
            for row in expected["profiles"]
        ]
        final = (
            json.loads(final_body["original_receipt"]) if final_body else None
        )
        profiles = []
        for member in members:
            admitted = (
                issued is not None
                and issued["window"]["binding"] == member["binding"]
            )
            proof = {
                **member,
                "phase": "sealed",
                "never_admitted": not admitted,
                "totals": {
                    "binding": member["binding"],
                    "upload_bytes": 0,
                    "download_bytes": 0,
                },
                "active_operations": 0,
                "resources": 0,
                "reserved_bytes": 0,
                "active_reservations": 0,
                "admission_operations": 0,
            }
            if (
                admitted
                and issued is not None
                and final is not None
                and final_body is not None
            ):
                proof["window"] = issued["window"]
                proof["snapshot"] = final_body["receipt"]
                proof["totals"] = next(
                    row
                    for row in final["profiles"]
                    if row["binding"] == member["binding"]
                )
            profiles.append(proof)
        document = {
            "receipt_version": 1,
            "state": "historical_epoch_sealed",
            "request": {
                "epoch": epoch,
                "request_id": uuid4().hex,
                "profiles": members,
            },
            "installation": expected["installation"],
            "adapter_revision": expected["adapter_revision"],
            "source_commit": expected["source_commit"],
            "module": "github.com/xtls/xray-core@v1.260327.0",
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "startup_receipt_sha256": startup_sha,
            "enforcement_sha256": expected["enforcement_sha256"],
            "window_policy_sha256": expected["window_policy_sha256"],
            "observed_at": datetime.now(UTC).isoformat(),
            "admission_blocked": True,
            "historical_only": True,
            "api_authority": False,
            "profiles": profiles,
        }
        original = json.dumps(document, indent=2)
        return {
            "original_receipt": original,
            "receipt": {
                "epoch": epoch,
                "request_id": document["request"]["request_id"],
                "receipt_sha256": hashlib.sha256(
                    original.encode()
                ).hexdigest(),
                "bytes": len(original.encode()),
            },
        }


class ManagedEpochSealsWorkflowTest(ManagedEpochSealWorkflowFixture):
    async def test_sealed_epoch_accepts_one_replayable_successor_epoch(self):
        _, node, expected, _, _, _ = await self.setup_closed()
        prior_epoch = "e" * 32
        self.enable_seals()
        startup_sha = await self.startup_sha(prior_epoch)
        seal = await asyncio.to_thread(
            self.submission, expected, startup_sha, prior_epoch
        )
        seal_path = (
            f"/v1/nodes/{node['node']['code']}/managed-epochs/"
            f"{prior_epoch}/seal"
        )
        next_epoch = "f" * 32
        startup = {
            "state": "isolated_closed_startup_observation",
            "epoch": next_epoch,
            "installation": expected["installation"],
            "adapter_revision": expected["adapter_revision"],
            "source_commit": expected["source_commit"],
            "module": "github.com/xtls/xray-core@v1.260327.0",
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "accounting_mode": "window_component",
            "enforcement_mode": "strict_decoded",
            "enforcement_sha256": expected["enforcement_sha256"],
            "window_policy_sha256": expected["window_policy_sha256"],
            "profiles": expected["profiles"],
            "api_authority": False,
            "budget_enforced": False,
            "deadline_enforced": False,
            "historical_only": True,
            "observed_at": datetime.now(UTC).isoformat(),
        }
        original = json.dumps(startup, separators=(",", ":"))
        rollover_body = {
            "request_id": uuid4().hex,
            "original_receipt": original,
            "receipt": {
                "epoch": next_epoch,
                "receipt_sha256": hashlib.sha256(
                    original.encode()
                ).hexdigest(),
                "bytes": len(original.encode()),
            },
        }
        rollover_path = (
            f"/v1/nodes/{node['node']['code']}/managed-epochs/"
            f"{prior_epoch}/rollover"
        )
        unsealed = await self.client.post(
            rollover_path,
            headers=self.node_headers,
            json=rollover_body,
        )
        self.assertEqual(unsealed.status_code, 409, unsealed.text)
        self.assertIn("managed_rollover_finality_missing", unsealed.text)
        accepted_seal = await self.client.post(
            seal_path, headers=self.node_headers, json=seal
        )
        self.assertEqual(accepted_seal.status_code, 200, accepted_seal.text)
        rollovers = await asyncio.gather(
            *(
                self.client.post(
                    rollover_path,
                    headers=self.node_headers,
                    json=rollover_body,
                )
                for _ in range(2)
            )
        )
        rollover = rollovers[0]
        for response in rollovers:
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), rollover.json())
        replay = await self.client.post(
            rollover_path, headers=self.node_headers, json=rollover_body
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), rollover.json())
        conflict = await self.client.post(
            rollover_path,
            headers=self.node_headers,
            json={**rollover_body, "request_id": uuid4().hex},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertIn("managed_rollover_request_reused", conflict.text)
        async with self.connection.uow() as fresh:
            rows = await fresh.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_managed_epoches "
                    "WHERE installation_id=:installation_id"
                ),
                {
                    "installation_id": rollover.json()["data"][
                        "installation_id"
                    ]
                },
            )
            self.assertEqual(rows.scalar_one(), 2)

        next_startup_sha = await self.startup_sha(next_epoch)
        next_seal = await asyncio.to_thread(
            self.submission, expected, next_startup_sha, next_epoch
        )
        next_seal_response = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/managed-epochs/{next_epoch}/seal",
            headers=self.node_headers,
            json=next_seal,
        )
        self.assertEqual(
            next_seal_response.status_code, 200, next_seal_response.text
        )
        third_epoch = "a" * 32
        third_startup = {**startup, "epoch": third_epoch}
        third_original = json.dumps(third_startup, separators=(",", ":"))
        third_body = {
            "request_id": uuid4().hex,
            "original_receipt": third_original,
            "receipt": {
                "epoch": third_epoch,
                "receipt_sha256": hashlib.sha256(
                    third_original.encode()
                ).hexdigest(),
                "bytes": len(third_original.encode()),
            },
        }
        capped = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/managed-epochs/{next_epoch}/rollover",
            headers=self.node_headers,
            json=third_body,
        )
        self.assertEqual(capped.status_code, 409, capped.text)
        self.assertIn("managed_rollover_capacity", capped.text)

    async def test_upgrade_from_prior_schema_preserves_existing_epoch(self):
        _, _, _, initial, _, _ = await self.setup_closed()
        epoch = initial["process_epoch"]
        async with self.connection.uow() as fresh:
            before = (
                await fresh.execute(
                    text(
                        "SELECT installation_id,process_epoch,receipt_sha256,"
                        "encrypted_receipt FROM tbl_managed_epoches "
                        "WHERE process_epoch=:epoch"
                    ),
                    {"epoch": epoch},
                )
            ).one()
        database = self.settings.db
        assert database is not None
        migration = Config("alembic.ini")
        migration.set_main_option("sqlalchemy.url", database.dsn)
        await asyncio.to_thread(
            command.downgrade, migration, "0060_sms_decision_history"
        )
        async with self.connection.uow() as fresh:
            version = await fresh.execute(
                text("SELECT version_num FROM alembic_version")
            )
            self.assertEqual(version.scalar_one(), "0060_sms_decision_history")
        await asyncio.to_thread(command.upgrade, migration, "head")
        async with self.connection.uow() as fresh:
            after = (
                await fresh.execute(
                    text(
                        "SELECT installation_id,process_epoch,receipt_sha256,"
                        "encrypted_receipt FROM tbl_managed_epoches "
                        "WHERE process_epoch=:epoch"
                    ),
                    {"epoch": epoch},
                )
            ).one()
            seal_count = await fresh.execute(
                text("SELECT COUNT(*) FROM tbl_managed_epoch_seals")
            )
            self.assertEqual(tuple(after), tuple(before))
            self.assertEqual(seal_count.scalar_one(), 0)

    async def test_open_native_reservation_denied_then_settled_exact_replay(
        self,
    ):
        (
            subscription,
            node,
            issued,
            expected,
            window_body,
            window_path,
        ) = await self.setup_window()
        epoch = issued["window"]["epoch"]
        self.enable_seals()
        startup = await self.startup_sha(epoch)
        path = f"/v1/nodes/{node['node']['code']}/managed-epochs/{epoch}/seal"
        never = await asyncio.to_thread(
            self.submission, expected, startup, epoch
        )
        before = await self.accounting(subscription["id"])
        financial = await self.financial_count()
        denied = await self.client.post(
            path, headers=self.node_headers, json=never
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(await self.seal_count(), 0)
        self.assertEqual(await self.accounting(subscription["id"]), before)
        _, final = await self.finalize_window(node, issued, expected)
        body = await asyncio.to_thread(
            self.submission, expected, startup, epoch, issued, final
        )
        accepted = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        window_replay = await self.client.post(
            window_path, headers=self.node_headers, json=window_body
        )
        self.assertEqual(window_replay.status_code, 200, window_replay.text)
        self.assertEqual(window_replay.json()["data"], issued)
        self.assertEqual(await self.seal_count(), 1)
        self.assertEqual(
            await self.accounting(subscription["id"]), (150, 0, 1, 1, 150)
        )
        self.assertEqual(await self.financial_count(), financial)
        policy, runtime = (
            self.settings.managed_adapter,
            self.settings.core_runtime,
        )
        try:
            self.settings.managed_adapter = None
            self.settings.core_runtime = None
            replay = await self.client.post(
                path, headers=self.node_headers, json=body
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json(), accepted.json())
            changed = {
                **body,
                "original_receipt": body["original_receipt"] + " ",
            }
            reused = await self.client.post(
                path, headers=self.node_headers, json=changed
            )
            self.assertEqual(reused.status_code, 409, reused.text)
            self.assertEqual(await self.seal_count(), 1)
            self.assertEqual(
                await self.accounting(subscription["id"]), (150, 0, 1, 1, 150)
            )
            self.assertEqual(await self.financial_count(), financial)
        finally:
            self.settings.managed_adapter = policy
            self.settings.core_runtime = runtime

    async def test_never_admitted_full_epoch_seal_has_no_business_effects(
        self,
    ):
        (
            subscription,
            node,
            expected,
            initial,
            initial_path,
            _,
        ) = await self.setup_closed()
        self.enable_seals()
        epoch = initial["process_epoch"]
        startup = await self.startup_sha(epoch)
        body = await asyncio.to_thread(
            self.submission, expected, startup, epoch
        )
        before = await self.accounting(subscription["id"])
        financial = await self.financial_count()
        path = f"/v1/nodes/{node['node']['code']}/managed-epochs/{epoch}/seal"
        accepted = await self.client.post(
            path, headers=self.node_headers, json=body
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(await self.seal_count(), 1)
        self.assertEqual(await self.accounting(subscription["id"]), before)
        self.assertEqual(await self.financial_count(), financial)
        policy = self.settings.managed_adapter
        assert policy is not None
        self.settings.managed_adapter = policy.model_copy(
            update={"window_mode": "reserved"}
        )
        denied = await self.client.post(
            initial_path, headers=self.node_headers, json=initial
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(await self.accounting(subscription["id"]), before)
