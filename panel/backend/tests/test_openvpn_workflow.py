import asyncio
from uuid import uuid4

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import text

from tests.test_fulfillment_workflow import FulfillmentWorkflowFixture
from tests.test_staff_administration_workflow import (
    StaffAdministrationWorkflowTest,
)


class OpenVpnWorkflowTest(
    StaffAdministrationWorkflowTest, FulfillmentWorkflowFixture
):
    @staticmethod
    def options(transport="udp", topology=None, key_type="ec_p256"):
        return {
            "protocol": "openvpn",
            "listen_address": "0.0.0.0",
            "ca_name": "Owned test authority",
            "server_name": "openvpn.example.invalid",
            "transport": transport,
            "topology": topology or {"mode": "tun", "network": "10.43.0.0/24"},
            "routes": ["10.78.0.0/16"],
            "dns": ["1.1.1.1"],
            "redirect_gateway": True,
            "client_to_client": False,
            "data_ciphers": ["AES-256-GCM", "AES-128-GCM"],
            "tls_min_version": "1.3",
            "tls_crypt": True,
            "key_type": key_type,
            "ca_validity_days": 730,
            "server_validity_days": 365,
            "client_validity_days": 90,
            "crl_validity_seconds": 3600,
            "keepalive_seconds": 10,
            "restart_seconds": 60,
            "max_clients": 10,
            "management_socket": (
                f"/run/papilio/openvpn-test-{transport}.sock"
            ),
            "verbosity": 3,
        }

    @staticmethod
    def inline(content, tag):
        return content.split(f"<{tag}>\n", 1)[1].split(f"</{tag}>", 1)[0]

    async def test_native_purchase_certificates_claim_privacy_and_revocation(
        self,
    ):
        subscription, request, nodes, _ = await self.setup_sale(
            protocols=("openvpn",), configuration_options=[self.options()]
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        tasks = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"]
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        node, claim = await self.claim(task, nodes)
        self.assertEqual(claim["core_kind"], "openvpn")
        self.assertNotIn("ca_private_key", claim["settings"]["openvpn"])
        self.assertNotIn("private_key", claim["credentials"]["openvpn"])
        configuration_id = claim["configuration_id"]
        private = await self.post(
            f"/v1/admin/network/configurations/profiles/{claim['profile_id']}/client-download"
        )
        self.assertTrue(private["filename"].endswith(".ovpn"))
        certificate = x509.load_pem_x509_certificate(
            self.inline(private["content"], "cert").encode()
        )
        authority = x509.load_pem_x509_certificate(
            self.inline(private["content"], "ca").encode()
        )
        certificate.verify_directly_issued_by(authority)
        key = serialization.load_pem_private_key(
            self.inline(private["content"], "key").encode(), None
        )
        self.assertEqual(
            key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ),
            certificate.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ),
        )
        self.assertEqual(
            str(certificate.serial_number),
            claim["credentials"]["openvpn"]["serial"],
        )
        before = await self.post(
            f"/v1/admin/network/configurations/{configuration_id}/server-download"
        )
        authority_key = authority.public_key()
        assert isinstance(
            authority_key, (ec.EllipticCurvePublicKey, rsa.RSAPublicKey)
        )
        crl = x509.load_pem_x509_crl(
            self.inline(before["content"], "crl-verify").encode()
        )
        self.assertTrue(crl.is_signature_valid(authority_key))
        self.assertIsNone(
            crl.get_revoked_certificate_by_serial_number(
                certificate.serial_number
            )
        )
        self.assertIn("management-client-auth\n", before["content"])
        self.assertIn("management-client\n", before["content"])
        self.assertNotIn("ca_private_key", before["content"])
        await self.ack(task, node, claim)
        sid = subscription["id"]
        active = (await self.get(f"/v1/admin/subscriptions/{sid}"))["data"]
        self.assertEqual(active["status"], "active")
        link = await self.post(
            f"/v1/admin/network/configurations/subscriptions/{sid}/link"
        )
        from urllib.parse import urlsplit

        path = urlsplit(link["url"]).path
        delivered = await self.get(path + "/profiles")
        host_id = delivered["data"][0]["host_id"]
        profile_path = (
            path
            + f"/profiles/{claim['profile_id']}/download?host_id={host_id}"
        )
        public = await self.client.get(profile_path)
        self.assertEqual(public.status_code, 200)
        self.assertEqual(
            self.inline(public.json()["data"]["content"], "cert"),
            self.inline(private["content"], "cert"),
        )
        feed = await self.client.get(path)
        self.assertEqual(feed.status_code, 404)
        suspension = await self.client.put(
            f"/v1/admin/subscriptions/{sid}/suspension",
            headers=self.headers,
            json={
                "request_key": uuid4().hex,
                "reason": "ابطال گواهی آزمایشی",
                "clock": "pause",
            },
        )
        self.assertEqual(suspension.status_code, 200)
        after = await self.post(
            f"/v1/admin/network/configurations/{configuration_id}/server-download"
        )
        revoked = x509.load_pem_x509_crl(
            self.inline(after["content"], "crl-verify").encode()
        )
        self.assertIsNotNone(
            revoked.get_revoked_certificate_by_serial_number(
                certificate.serial_number
            )
        )
        self.assertTrue(revoked.is_signature_valid(authority_key))
        self.assertEqual(
            (await self.client.get(profile_path)).status_code,
            404,
        )
        async with self.connection.uow() as unit:
            entries = (
                await unit.execute(
                    text(
                        "SELECT COUNT(*) FROM tbl_wallet_entries "
                        "WHERE reason='purchase'"
                    )
                )
            ).scalar_one()
            self.assertEqual(entries, 1)

    async def test_tcp_bridge_udp_routing_capacity_identity_and_single_replay(
        self,
    ):
        registered = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "ovpn_" + self.suffix,
                "label": "نود گواهی",
                "public_host": "vpn.example.invalid",
                "public_port": 1194,
                "protocol": "openvpn",
            },
        )
        node = registered["node"]
        tcp = self.options(
            "tcp",
            {
                "mode": "tap",
                "network": "10.64.0.0/24",
                "bridge_address": "10.64.0.1",
                "pool_start": "10.64.0.10",
                "pool_end": "10.64.0.20",
            },
            "rsa_2048",
        )
        tcp.update(
            tls_crypt=False, redirect_gateway=False, client_to_client=True
        )
        udp = self.options()
        drafts = await asyncio.gather(
            *(
                self.post(
                    "/v1/admin/network/configurations",
                    {
                        "node_id": node["id"],
                        "label": "انتقال " + option["transport"],
                        "options": option,
                    },
                )
                for option in (udp, tcp)
            )
        )
        self.assertEqual(
            [row["port_network"] for row in drafts], ["udp", "tcp"]
        )
        customer, subscription = await self.paid_subscription()
        bodies = [{"subscription_id": subscription["id"]} for _ in drafts]
        profiles = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/{row['id']}/profiles",
                    body,
                )
                for row, body in zip(drafts, bodies, strict=True)
            )
        )
        replay = await self.post(
            f"/v1/admin/network/configurations/{drafts[0]['id']}/profiles",
            bodies[0],
        )
        self.assertEqual(replay["id"], profiles[0]["id"])
        files = await asyncio.gather(
            *(
                self.post(
                    f"/v1/admin/network/configurations/profiles/{row['id']}/client-download"
                )
                for row in profiles
            )
        )
        self.assertIn("proto udp\n", files[0]["content"])
        self.assertIn("dev tun\n", files[0]["content"])
        self.assertIn("<tls-crypt>", files[0]["content"])
        self.assertIn("proto tcp-client\n", files[1]["content"])
        self.assertIn("dev tap\n", files[1]["content"])
        self.assertNotIn("<tls-crypt>", files[1]["content"])
        server = await self.post(
            f"/v1/admin/network/configurations/{drafts[1]['id']}/server-download"
        )
        self.assertIn(
            "server-bridge 10.64.0.1 255.255.255.0 10.64.0.10 10.64.0.20",
            server["content"],
        )
        self.assertNotIn("redirect-gateway", server["content"])
        self.assertIn("client-to-client\n", server["content"])
        changed = await self.client.put(
            f"/v1/admin/network/configurations/{drafts[1]['id']}",
            headers=self.headers,
            json={
                "expected_revision": 1,
                "label": "تغییر هویت",
                "options": {**tcp, "server_name": "other.example.invalid"},
            },
        )
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(
            changed.json()["error"]["message_code"], "openvpn_identity_changed"
        )
        capacity = self.settings.openvpn
        assert capacity is not None
        max_clients = capacity.max_clients
        try:
            capacity.max_clients = 1
            limited = await self.client.post(
                "/v1/admin/network/configurations",
                headers=self.headers,
                json={
                    "node_id": node["id"],
                    "listen_port": 2194,
                    "label": "خارج از ظرفیت",
                    "options": udp,
                },
            )
            self.assertEqual(limited.status_code, 409)
            self.assertEqual(
                limited.json()["error"]["message_code"], "openvpn_capacity"
            )
            capacity.max_clients = max_clients
            capacity.enabled = False
            disabled = await self.client.post(
                "/v1/admin/network/configurations",
                headers=self.headers,
                json={
                    "node_id": node["id"],
                    "listen_port": 2194,
                    "label": "سیاست غیرفعال",
                    "options": udp,
                },
            )
            self.assertEqual(disabled.status_code, 409)
            self.assertEqual(
                disabled.json()["error"]["message_code"], "openvpn_disabled"
            )
        finally:
            capacity.max_clients = max_clients
            capacity.enabled = True
        recovered = await self.post(
            "/v1/admin/network/configurations",
            {
                "node_id": node["id"],
                "listen_port": 2194,
                "label": "بازیابی ظرفیت",
                "options": {
                    **udp,
                    "management_socket": "/run/papilio/recovered.sock",
                },
            },
        )
        self.assertEqual(recovered["port_network"], "udp")
        async with self.connection.uow() as unit:
            count = (
                await unit.execute(
                    text("SELECT COUNT(*) FROM tbl_configurations")
                )
            ).scalar_one()
            self.assertEqual(count, 3)
            profile_count = (
                await unit.execute(text("SELECT COUNT(*) FROM tbl_profiles"))
            ).scalar_one()
            self.assertEqual(profile_count, 2)

    @staticmethod
    def expired_payloads(
        settings_ciphertext,
        credentials_ciphertext,
        payload_ciphertext,
        encryption_key,
    ):
        from datetime import UTC, datetime, timedelta

        from cryptography.hazmat.primitives import hashes
        from cryptography.x509.oid import ExtendedKeyUsageOID
        from papilio.security.crypto import decrypt, encrypt

        from src.modules.network.configurations.app.openvpn_pki import (
            OpenVpnCertificateAuthority,
        )
        from src.modules.network.configurations.domain.openvpn import (
            OpenVpnClientCertificate,
        )
        from src.modules.network.configurations.domain.results import (
            ClientCredentials,
            StoredSettings,
        )
        from src.modules.network.provisioning.domain.results import (
            ProvisionPayload,
        )

        settings = StoredSettings.model_validate_json(
            decrypt(settings_ciphertext, encryption_key)
        )
        credentials = ClientCredentials.model_validate_json(
            decrypt(credentials_ciphertext, encryption_key)
        )
        assert settings.openvpn is not None and credentials.openvpn is not None
        old = x509.load_pem_x509_certificate(
            credentials.openvpn.certificate.encode()
        )
        now = datetime.now(UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(old.subject)
            .issuer_name(old.issuer)
            .public_key(old.public_key())
            .serial_number(old.serial_number)
            .not_valid_before(now - timedelta(days=2))
            .not_valid_after(now - timedelta(days=1))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .sign(
                OpenVpnCertificateAuthority.load_private(
                    settings.openvpn.ca_private_key
                ),
                hashes.SHA256(),
            )
        )
        expired = OpenVpnClientCertificate(
            certificate=certificate.public_bytes(
                serialization.Encoding.PEM
            ).decode(),
            private_key=credentials.openvpn.private_key,
            serial=credentials.openvpn.serial,
        )
        credentials.openvpn = expired
        payload = ProvisionPayload.model_validate_json(
            decrypt(payload_ciphertext, encryption_key)
        )
        payload.credentials.openvpn = expired
        return encrypt(credentials.model_dump_json(), encryption_key), encrypt(
            payload.model_dump_json(), encryption_key
        )

    async def test_expired_certificate_denial_retains_paid_order(self):
        subscription, request, nodes, _ = await self.setup_sale(
            protocols=("openvpn",), configuration_options=[self.options()]
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        task = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"][0]
        async with self.connection.uow() as unit:
            stored = (
                await unit.execute(
                    text(
                        "SELECT c.encrypted_settings, "
                        "p.encrypted_credentials, t.encrypted_payload "
                        "FROM tbl_provision_tasks t JOIN tbl_profiles p ON "
                        "p.id=t.profile_id "
                        "JOIN tbl_configurations c ON "
                        "c.id=t.configuration_id WHERE t.id=:id"
                    ),
                    {"id": task["id"]},
                )
            ).one()
        credentials, payload = await asyncio.to_thread(
            self.expired_payloads,
            stored[0],
            stored[1],
            stored[2],
            self.settings.configuration_encryption_key,
        )
        async with self.connection.uow() as unit:
            await unit.execute(
                text(
                    "UPDATE tbl_profiles SET encrypted_credentials=:cipher "
                    "WHERE id=:id"
                ),
                {"id": task["profile_id"], "cipher": credentials},
            )
            await unit.execute(
                text(
                    "UPDATE tbl_provision_tasks SET "
                    "encrypted_payload=:cipher WHERE id=:id"
                ),
                {"id": task["id"], "cipher": payload},
            )
            await unit.commit()
        private = await self.client.post(
            f"/v1/admin/network/configurations/profiles/{task['profile_id']}/client-download",
            headers=self.headers,
        )
        self.assertEqual(private.status_code, 409)
        self.assertEqual(
            private.json()["error"]["message_code"],
            "openvpn_certificate_unavailable",
        )
        node = nodes[0]
        rejected = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/provisioning/{task['id']}/claim",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(
            rejected.json()["error"]["message_code"],
            "openvpn_certificate_unavailable",
        )
        async with self.connection.uow() as unit:
            current = (
                await unit.execute(
                    text(
                        "SELECT state, attempts, claim_hash FROM "
                        "tbl_provision_tasks WHERE id=:id"
                    ),
                    {"id": task["id"]},
                )
            ).one()
            self.assertEqual(current, ("queued", 0, None))
            paid = (
                await unit.execute(
                    text(
                        "SELECT status,price_rial FROM tbl_subscriptions "
                        "WHERE id=:id"
                    ),
                    {"id": subscription["id"]},
                )
            ).one()
            self.assertEqual(paid, ("pending_provision", 100000))
            ledger = (
                await unit.execute(
                    text(
                        "SELECT reason,COUNT(*) FROM tbl_wallet_entries "
                        "GROUP BY reason"
                    )
                )
            ).all()
            self.assertEqual(
                {reason: count for reason, count in ledger},
                {"approved_topup": 1, "purchase": 1},
            )

    @staticmethod
    def management_binding(claim):
        certificate = x509.load_pem_x509_certificate(
            claim["credentials"]["openvpn"]["certificate"].encode()
        )
        serial = format(certificate.serial_number, "x")
        serial = serial if len(serial) % 2 == 0 else "0" + serial
        return {
            "ProfileID": claim["profile_id"],
            "SubscriptionID": claim["subscription_id"],
            "Generation": claim["generation"],
            "Identity": claim["credentials"]["identity"],
            "SerialHex": ":".join(
                serial[index : index + 2] for index in range(0, len(serial), 2)
            ),
            "CertificateExpiresAt": (
                certificate.not_valid_after_utc.isoformat()
            ),
        }

    @staticmethod
    def run_management_gate(fixture):
        import json
        import os
        import subprocess
        import tempfile
        import time
        from pathlib import Path

        deadline = time.monotonic() + fixture["timeout_ms"] / 1000
        ready = False
        with httpx.Client(timeout=1) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(fixture["api_url"] + "/")
                    ready = response.status_code == 404
                except httpx.TransportError:
                    pass
                if ready:
                    break
                time.sleep(0.02)
        if not ready:
            raise RuntimeError("Owned management test API did not start")
        with tempfile.TemporaryDirectory(
            prefix="papilio-openvpn-gate-"
        ) as tmp:
            path = Path(tmp) / "private-fixture.json"
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w") as stream:
                json.dump(fixture, stream)
            environment = dict(os.environ)
            environment["PAPILIO_OPENVPN_TEST_FIXTURE"] = str(path)
            result = subprocess.run(
                [
                    "go",
                    "test",
                    "./internal/openvpn",
                    "./ipadmission",
                    "-run",
                    "TestLiveNativeManagement|TestProtectedConnection",
                    "-count=1",
                    "-timeout=30s",
                ],
                cwd=Path(__file__).resolve().parents[3] / "proxy",
                env=environment,
                capture_output=True,
                text=True,
                timeout=45,
            )
        return result.returncode, result.stdout + result.stderr

    async def test_dormant_management_native_admission_and_accounting(self):
        import socket

        import uvicorn

        subscription, request, nodes, _ = await self.setup_sale(
            protocols=("openvpn",), configuration_options=[self.options()]
        )
        await self.post(f"/v1/admin/provisioning/{request['id']}/prepare")
        task = (
            await self.get(f"/v1/admin/provisioning/{request['id']}/tasks")
        )["data"][0]
        node, claim = await self.claim(task, nodes)
        await self.ack(task, node, claim)
        configured = await self.client.put(
            f"/v1/admin/subscriptions/{subscription['id']}/ip-limit",
            headers=self.headers,
            json={
                "enabled": True,
                "max_ips": 1,
                "lease_seconds": 3,
                "ban_seconds": 300,
                "mode": "reject_new",
            },
        )
        self.assertEqual(configured.status_code, 200)
        grant = await self.client.post(
            f"/v1/nodes/{node['node']['code']}/usage/grants",
            headers={"X-Papilio-Node-Key": node["agent_key"]},
            json={
                "profile_id": claim["profile_id"],
                "generation": claim["generation"],
                "request_key": "openvpn-management-" + self.suffix,
                "requested_bytes": 1000,
            },
        )
        self.assertEqual(grant.status_code, 200)
        binding = await asyncio.to_thread(self.management_binding, claim)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                lifespan="off",
                access_log=False,
                log_level="error",
            )
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            result, output = await asyncio.to_thread(
                self.run_management_gate,
                {
                    "api_url": f"http://127.0.0.1:{port}",
                    "node_code": node["node"]["code"],
                    "node_key": node["agent_key"],
                    "binding": binding,
                    "grant_id": grant.json()["data"]["id"],
                    "timeout_ms": 5000,
                    "max_response_bytes": 16384,
                    "max_line_bytes": 4096,
                    "max_environment_fields": 32,
                    "max_sessions": self.options()["max_clients"],
                    "renew_before_ms": 1000,
                    "bytecount_seconds": 1,
                },
            )
            self.assertEqual(result, 0, output)
        finally:
            server.should_exit = True
            await serving
            listener.close()
        async with self.connection.uow() as unit:
            used = (
                await unit.execute(
                    text(
                        "SELECT used_bytes,status FROM tbl_subscriptions "
                        "WHERE id=:id"
                    ),
                    {"id": subscription["id"]},
                )
            ).one()
            self.assertEqual(used, (150, "active"))
            epoch = (
                await unit.execute(
                    text(
                        "SELECT upload_bytes,download_bytes,sequence,"
                        "is_closed "
                        "FROM tbl_usage_grants WHERE id=:id"
                    ),
                    {"id": grant.json()["data"]["id"]},
                )
            ).one()
            self.assertEqual(epoch, (61, 89, 2, 1))
            sessions = (
                await unit.execute(
                    text(
                        "SELECT source_ip,block_reason FROM tbl_ip_sessions "
                        "WHERE subscription_id=:id ORDER BY source_ip"
                    ),
                    {"id": subscription["id"]},
                )
            ).all()
            self.assertEqual(
                sessions,
                [("192.0.2.71", None), ("192.0.2.72", "ip_limit_exceeded")],
            )

    async def test_management_socket_ownership_concurrency_and_edit_recovery(
        self,
    ):
        node = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "socket_" + self.suffix,
                "label": "نود سوکت مستقل",
                "public_host": "example.invalid",
                "public_port": 1194,
                "protocol": "openvpn",
            },
        )
        base = {
            "node_id": node["node"]["id"],
            "listen_port": 1194,
            "label": "ورودی اول",
            "options": self.options(),
        }
        initial = await self.post("/v1/admin/network/configurations", base)
        conflicting = {
            **base,
            "listen_port": 1195,
            "options": {
                **self.options("tcp"),
                "management_socket": self.options()["management_socket"],
            },
        }
        denied = await self.client.post(
            "/v1/admin/network/configurations",
            headers=self.headers,
            json=conflicting,
        )
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(
            denied.json()["error"]["message_code"],
            "openvpn_management_conflict",
        )
        racing = {
            **self.options(),
            "management_socket": "/run/papilio/race.sock",
        }
        requests = await asyncio.gather(
            self.client.post(
                "/v1/admin/network/configurations",
                headers=self.headers,
                json={**base, "listen_port": 1196, "options": racing},
            ),
            self.client.post(
                "/v1/admin/network/configurations",
                headers=self.headers,
                json={**base, "listen_port": 1197, "options": racing},
            ),
        )
        self.assertEqual(sorted(r.status_code for r in requests), [200, 409])
        alias = await self.client.post(
            "/v1/admin/network/configurations",
            headers=self.headers,
            json={
                **base,
                "listen_port": 1198,
                "options": {
                    **self.options(),
                    "management_socket": "/run//papilio/./race.sock",
                },
            },
        )
        self.assertEqual(alias.status_code, 409)
        too_long = await self.client.post(
            "/v1/admin/network/configurations",
            headers=self.headers,
            json={
                **base,
                "listen_port": 1199,
                "options": {
                    **self.options(),
                    "management_socket": "/run/" + "x" * 108,
                },
            },
        )
        self.assertEqual(too_long.status_code, 422)
        update_path = f"/v1/admin/network/configurations/{initial['id']}"
        edit = await self.client.put(
            update_path,
            headers=self.headers,
            json={
                "label": "ویرایش محفوظ",
                "expected_revision": 1,
                "options": racing,
            },
        )
        self.assertEqual(edit.status_code, 409)
        untouched = (await self.get(update_path))["data"]
        self.assertEqual(untouched["revision"], 1)
        self.assertEqual(
            untouched["options"]["management_socket"],
            base["options"]["management_socket"],
        )
        edits = await asyncio.gather(
            self.client.put(
                update_path,
                headers=self.headers,
                json={
                    "label": "مسیر تازه",
                    "expected_revision": 1,
                    "options": {
                        **self.options(),
                        "management_socket": "/run/papilio/Changed.sock",
                    },
                },
            ),
            self.client.put(
                update_path,
                headers=self.headers,
                json={
                    "label": "مسیر تازه",
                    "expected_revision": 1,
                    "options": {
                        **self.options(),
                        "management_socket": "/run/papilio/other.sock",
                    },
                },
            ),
        )
        self.assertEqual(sorted(r.status_code for r in edits), [200, 409])
        saved = (await self.get(update_path))["data"]
        self.assertEqual(saved["revision"], 2)
        path = saved["options"]["management_socket"]
        parent, filename = path.rsplit("/", 1)
        await self.post(
            "/v1/admin/network/configurations",
            {
                **base,
                "listen_port": 1199,
                "options": {
                    **self.options(),
                    "management_socket": parent + "/" + filename.swapcase(),
                },
            },
        )
        second_node = await self.post(
            "/v1/admin/network/nodes",
            {
                "code": "socket_other_" + self.suffix,
                "label": "نود دوم",
                "public_host": "other.example.invalid",
                "public_port": 1194,
                "protocol": "openvpn",
            },
        )
        await self.post(
            "/v1/admin/network/configurations",
            {**base, "node_id": second_node["node"]["id"]},
        )
        async with self.connection.uow() as unit:
            counts = (
                await unit.execute(
                    text(
                        "SELECT (SELECT COUNT(*) FROM tbl_configurations),"
                        "(SELECT COUNT(*) FROM tbl_inbound_ports),"
                        "(SELECT COUNT(*) FROM tbl_open_vpn_sockets)"
                    )
                )
            ).one()
            self.assertEqual(counts, (4, 4, 4))
            reserved = (
                await unit.execute(
                    text(
                        "SELECT path FROM tbl_open_vpn_sockets "
                        "WHERE configuration_id=:id"
                    ),
                    {"id": initial["id"]},
                )
            ).scalar_one()
            self.assertEqual(reserved, saved["options"]["management_socket"])

    async def test_populated_management_upgrade_preflight_and_preservation(
        self,
    ):
        import json
        import os
        from unittest.mock import patch
        from uuid import uuid4

        from alembic import command
        from alembic.config import Config
        from papilio.infra.db.connection import DBConnection
        from papilio.infra.db.uow import MySQLUnitOfWork
        from papilio.security.crypto import encrypt
        from sqlalchemy.engine import make_url

        assert self.settings.db is not None
        schema = "papilio_openvpn_upgrade_" + uuid4().hex[:12]
        target_url = make_url(str(self.settings.db.dsn)).set(database=schema)
        target_dsn = target_url.render_as_string(hide_password=False)
        target = DBConnection(
            dsn=target_dsn,
            pool_size=2,
            max_overflow=0,
            pool_timeout=30,
            pool_recycle=1800,
            uow_factory=MySQLUnitOfWork,
        )
        async with self.maintenance.uow() as unit:
            await unit.execute(text(f"CREATE DATABASE `{schema}`"))
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", target_dsn)
        try:
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                await asyncio.to_thread(
                    command.upgrade,
                    config,
                    "0035_reseller_customer_access",
                )
            encrypted_settings = encrypt(
                json.dumps({"options": self.options()}),
                self.settings.configuration_encryption_key,
            )
            async with target.uow() as unit:
                await unit.execute(
                    text(
                        "INSERT INTO tbl_nodes "
                        "(id,code,label,public_host,public_port,protocol,"
                        "agent_key_hash,is_enabled) VALUES "
                        "(1,'legacy-openvpn','Legacy OpenVPN',"
                        "'openvpn.example.invalid',1194,'openvpn',"
                        "'legacy-test-agent-key',1)"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_cores "
                        "(id,node_id,code,label,kind) VALUES "
                        "(1,1,'legacy_openvpn','Legacy OpenVPN','openvpn')"
                    )
                )
                await unit.execute(
                    text(
                        "INSERT INTO tbl_configurations "
                        "(id,revision,node_id,core_id,listen_port,"
                        "port_network,label,protocol,encrypted_settings) "
                        "VALUES "
                        "(1,1,1,1,1194,'udp','legacy-openvpn-1','openvpn',"
                        ":settings),(2,1,1,1,1195,'udp',"
                        "'legacy-openvpn-2','openvpn',:settings)"
                    ),
                    {"settings": encrypted_settings},
                )
                await unit.commit()
            with patch.dict(
                os.environ, {"PAPILIO_CONFIG": "config.yml.sample"}
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "overlapping OpenVPN"
                ):
                    await asyncio.to_thread(
                        command.upgrade,
                        config,
                        "0036_openvpn_management_sockets",
                    )
                async with target.uow() as unit:
                    created = (
                        await unit.execute(
                            text(
                                "SELECT COUNT(*) "
                                "FROM information_schema.tables "
                                "WHERE table_schema=DATABASE() "
                                "AND table_name='tbl_open_vpn_sockets'"
                            )
                        )
                    ).scalar_one()
                    self.assertEqual(created, 0)
                    revision = (
                        await unit.execute(
                            text("SELECT version_num FROM alembic_version")
                        )
                    ).scalar_one()
                    self.assertEqual(revision, "0035_reseller_customer_access")
                    await unit.execute(
                        text("DELETE FROM tbl_configurations WHERE id=2")
                    )
                    await unit.commit()
                await asyncio.to_thread(
                    command.upgrade,
                    config,
                    "0036_openvpn_management_sockets",
                )
                with self.assertRaisesRegex(RuntimeError, "active management"):
                    await asyncio.to_thread(
                        command.downgrade,
                        config,
                        "0035_reseller_customer_access",
                    )
            async with target.uow() as unit:
                config_row = (
                    await unit.execute(
                        text(
                            "SELECT encrypted_settings FROM "
                            "tbl_configurations WHERE id=1"
                        )
                    )
                ).scalar_one()
                self.assertEqual(config_row, encrypted_settings)
                endpoint = (
                    await unit.execute(
                        text(
                            "SELECT configuration_id,path "
                            "FROM tbl_open_vpn_sockets"
                        )
                    )
                ).one()
                self.assertEqual(
                    endpoint,
                    (1, self.options()["management_socket"]),
                )
        finally:
            await target.dispose()
            async with self.maintenance.uow() as unit:
                await unit.execute(text(f"DROP DATABASE `{schema}`"))
