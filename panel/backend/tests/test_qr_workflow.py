import asyncio
import threading
import time
from io import BytesIO
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from PIL import Image
from sqlalchemy import text

from src.modules.network.qr_codes.app.images import QrImages
from tests.test_trials_workflow import TrialsWorkflowTest


class QrWorkflowTest(TrialsWorkflowTest):
    async def ready_subscription(self):
        subscription, request, nodes, _ = await self.setup_sale(
            automatic=False, protocols=("vless_reality", "wireguard")
        )
        url = (
            await self.post(
                "/v1/admin/network/configurations/subscriptions/"
                f"{subscription['id']}/link"
            )
        )["url"]
        path = urlsplit(url).path
        self.assertEqual(
            (await self.client.get(path + "/qr")).status_code, 404
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        claims = await asyncio.gather(
            *(self.claim(task, nodes) for task in tasks)
        )
        await asyncio.gather(
            *(
                self.ack(task, *claim)
                for task, claim in zip(tasks, claims, strict=True)
            )
        )
        profiles = (await self.get(path + "/profiles"))["data"]
        self.assertEqual(len(profiles), 2)
        return subscription, path, profiles

    async def policy(self, **changes):
        prefs = (await self.get("/v1/admin/settings"))["data"]
        prefs["values"]["qr_codes"].update(changes)
        result = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        return result

    async def test_ready_owned_images_rotation_and_suspension(self):
        subscription, path, profiles = await self.ready_subscription()
        paths = [path + "/qr"] + [
            f"{path}/profiles/{row['profile_id']}/qr?host_id={row['host_id']}"
            for row in profiles
        ]
        images = await asyncio.gather(
            *(self.client.get(value) for value in paths)
        )
        for result in images:
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers["content-type"], "image/png")
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertEqual(result.headers["referrer-policy"], "no-referrer")
            with Image.open(BytesIO(result.content)) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.width, image.height)
                self.assertEqual(image.getpixel((0, 0)), 255)
                self.assertLessEqual(image.width, 2048)
        other_customer, other_subscription = await self.paid_subscription()
        other = (
            await self.post(
                "/v1/admin/network/configurations/subscriptions/"
                f"{other_subscription['id']}/link"
            )
        )["url"]
        cross = await self.client.get(
            urlsplit(other).path
            + f"/profiles/{profiles[0]['profile_id']}/qr"
            + f"?host_id={profiles[0]['host_id']}"
        )
        self.assertEqual(cross.status_code, 404)
        unknown_host = await self.client.get(
            path
            + f"/profiles/{profiles[0]['profile_id']}/qr"
            + "?host_id=9223372036854775807"
        )
        self.assertEqual(unknown_host.status_code, 404)
        rotated = (
            await self.post(
                "/v1/admin/network/configurations/subscriptions/"
                f"{subscription['id']}/rotate-link"
            )
        )["url"]
        old = await asyncio.gather(
            *(self.client.get(value) for value in paths)
        )
        self.assertTrue(all(result.status_code == 404 for result in old))
        current = urlsplit(rotated).path
        self.assertEqual(
            (await self.client.get(current + "/qr")).status_code, 200
        )
        suspended = await self.client.put(
            f"/v1/admin/subscriptions/{subscription['id']}/suspension",
            headers=self.headers,
            json={
                "request_key": uuid4().hex,
                "reason": "توقف دسترسی",
                "clock": "continue",
            },
        )
        self.assertEqual(suspended.status_code, 200)
        unavailable = await asyncio.gather(
            self.client.get(current + "/qr"),
            self.client.get(
                current
                + f"/profiles/{profiles[0]['profile_id']}/qr"
                + f"?host_id={profiles[0]['host_id']}"
            ),
        )
        self.assertTrue(
            all(result.status_code == 404 for result in unavailable)
        )
        async with self.connection.uow() as unit:
            ledger = (
                await unit.execute(
                    text(
                        "SELECT COUNT(*),SUM(amount_rial) FROM "
                        "tbl_wallet_entries WHERE wallet_id=(SELECT id "
                        "FROM tbl_wallets WHERE customer_id=:id)"
                    ),
                    {"id": subscription["customer_id"]},
                )
            ).one()
            self.assertEqual(tuple(ledger), (2, 200000))

    async def test_policy_capacity_fallback_legacy_and_render_responsiveness(
        self,
    ):
        _, path, profiles = await self.ready_subscription()
        prefs = (await self.get("/v1/admin/settings"))["data"]
        legacy_revision = await self.policy(error_correction="M")
        self.assertEqual(legacy_revision.status_code, 200)
        async with self.connection.uow() as unit:
            await unit.execute(
                text(
                    "UPDATE tbl_preferences_revisions SET values_json="
                    "JSON_REMOVE(values_json,'$.qr_codes') "
                    "WHERE revision=:revision"
                ),
                {"revision": legacy_revision.json()["data"]["revision"]},
            )
            await unit.commit()
        prefs = (await self.get("/v1/admin/settings"))["data"]
        self.assertTrue(prefs["values"]["qr_codes"]["enabled"])
        prefs["values"].pop("qr_codes")
        legacy = await self.client.put(
            "/v1/admin/settings",
            headers=self.headers,
            json={
                "expected_revision": prefs["revision"],
                "values": prefs["values"],
            },
        )
        self.assertEqual(legacy.status_code, 200)
        self.assertTrue(legacy.json()["data"]["values"]["qr_codes"]["enabled"])
        self.assertEqual((await self.policy(box_size=25)).status_code, 400)
        self.assertEqual(
            (await self.policy(border_modules=3)).status_code, 422
        )
        changed = await self.policy(
            error_correction="H", box_size=5, border_modules=6
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual((await self.policy(enabled=False)).status_code, 200)
        self.assertEqual(
            (await self.client.get(path + "/qr")).status_code, 409
        )
        self.assertFalse(
            (await self.get(path + "/status"))["data"]["qr_enabled"]
        )
        self.assertEqual((await self.client.get(path)).status_code, 200)
        self.assertEqual((await self.policy(enabled=True)).status_code, 200)
        capacity = self.settings.qr_codes
        assert capacity is not None
        original_payload = capacity.max_payload_bytes
        capacity.max_payload_bytes = 1
        self.assertEqual(
            (await self.client.get(path + "/qr")).status_code, 409
        )
        self.assertEqual((await self.client.get(path)).status_code, 200)
        capacity.max_payload_bytes = original_payload
        original_side = capacity.max_side_pixels
        capacity.max_side_pixels = 1
        self.assertEqual(
            (await self.client.get(path + "/qr")).status_code, 409
        )
        capacity.max_side_pixels = original_side
        original_png = capacity.max_png_bytes
        capacity.max_png_bytes = 1
        self.assertEqual(
            (await self.client.get(path + "/qr")).status_code, 409
        )
        capacity.max_png_bytes = original_png
        capacity.max_box_size = 4
        self.assertFalse(
            (await self.get(path + "/status"))["data"]["qr_enabled"]
        )
        self.assertEqual((await self.policy(enabled=False)).status_code, 200)
        self.assertEqual((await self.policy(enabled=True)).status_code, 400)
        capacity.max_box_size = 24
        self.assertEqual((await self.policy(enabled=True)).status_code, 200)
        entered, completed = threading.Event(), threading.Event()
        original = QrImages.render

        def delayed(renderer, payload, policy, limit):
            entered.set()
            time.sleep(0.15)
            result = original(renderer, payload, policy, limit)
            completed.set()
            return result

        async def heartbeat():
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            self.assertFalse(completed.is_set(), "QR blocked the event loop")

        with patch.object(QrImages, "render", new=delayed):
            result, _ = await asyncio.gather(
                self.client.get(
                    path
                    + f"/profiles/{profiles[0]['profile_id']}/qr"
                    + f"?host_id={profiles[0]['host_id']}"
                ),
                heartbeat(),
            )
        self.assertEqual(result.status_code, 200)
        self.settings.qr_codes = None
        self.assertEqual(
            (await self.client.get(path + "/qr")).status_code, 409
        )
        self.assertEqual((await self.policy(enabled=False)).status_code, 200)
        self.assertEqual((await self.client.get(path)).status_code, 200)
