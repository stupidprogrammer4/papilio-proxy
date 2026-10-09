import hashlib
import json
from datetime import datetime

from papilio.security.crypto import decrypt, encrypt

from src.modules.network.configurations.app.availability import (
    ServerProfileAvailability,
)
from src.modules.network.core_runtime.domain.facts import RuntimeSnapshotFacts
from src.modules.network.cores.domain.exports import CoreExport


class RuntimePayload:
    @staticmethod
    def digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf8")).hexdigest()

    @staticmethod
    def bundle_digest(export: CoreExport) -> str:
        text = json.dumps(
            [
                artifact.model_dump(exclude={"content"})
                for artifact in export.artifacts
            ],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return RuntimePayload.digest(text)

    @staticmethod
    def encode(export: CoreExport, key: str) -> str:
        return encrypt(export.model_dump_json(), key)

    @staticmethod
    def decode(payload: str, key: str) -> CoreExport:
        return CoreExport.model_validate_json(decrypt(payload, key))

    @staticmethod
    def fingerprints(
        facts: RuntimeSnapshotFacts, now: datetime
    ) -> tuple[str, str]:
        configurations = [
            (
                c.id,
                c.revision,
                c.listen_port,
                c.port_network,
                c.protocol,
                c.encrypted_settings,
            )
            for c in facts.configurations
        ]
        profiles = []
        for row in facts.profiles:
            eligible = ServerProfileAvailability.eligible(
                services_available=row.services_enabled
                and not row.service_hold_pending,
                status=row.status,
                request_state=row.request_state,
                expires_at=row.expires_at,
                quota_bytes=row.quota_bytes,
                used_bytes=row.used_bytes,
                now=now,
            )
            profiles.append(
                (
                    row.id,
                    row.configuration_id,
                    row.encrypted_credentials,
                    row.client_address,
                    row.subscription_id,
                    row.generation,
                    row.quota_bytes,
                    row.expires_at.isoformat() if row.expires_at else None,
                    eligible,
                )
            )
        entitlements = RuntimePayload.digest(
            json.dumps(profiles, separators=(",", ":"), ensure_ascii=False)
        )
        snapshot = RuntimePayload.digest(
            json.dumps(
                (configurations, profiles),
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )
        return snapshot, entitlements
