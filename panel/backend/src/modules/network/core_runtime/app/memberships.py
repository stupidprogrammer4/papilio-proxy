import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta

from papilio.security.crypto import decrypt, encrypt

from src.modules.network.configurations.app.availability import (
    ServerProfileAvailability,
)
from src.modules.network.configurations.domain.results import (
    ClientCredentials,
    NodeClientCredentials,
)
from src.modules.network.core_runtime.domain.facts import RuntimeSnapshotFacts
from src.modules.network.core_runtime.domain.memberships import (
    InstalledProfileMembership,
    RuntimeEntitlementBinding,
    RuntimeMembershipSnapshot,
)
from src.modules.network.cores.domain.exports import CoreExport
from src.modules.network.provisioning.app.payloads import (
    ProvisionNodeSecrets,
    ProvisionPayloadEncoding,
)
from src.modules.sales.catalog.domain.policies import FulfillmentPolicy


class InstalledProfileEncoding:
    @staticmethod
    def credential_digest(credentials: NodeClientCredentials) -> str:
        value = json.dumps(
            credentials.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(value.encode("utf8")).hexdigest()

    @staticmethod
    def membership_digest(snapshot: "RuntimeMembershipSnapshot") -> str:
        value = json.dumps(
            [row.model_dump(mode="json") for row in snapshot.memberships],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(value.encode("utf8")).hexdigest()

    @staticmethod
    def decode(ciphertext: str, key: str) -> "RuntimeMembershipSnapshot":
        return RuntimeMembershipSnapshot.model_validate_json(
            decrypt(ciphertext, key)
        )

    @staticmethod
    def encode(snapshot: "RuntimeMembershipSnapshot", key: str) -> str:
        return encrypt(snapshot.model_dump_json(), key)

    @staticmethod
    def capture(
        facts: "RuntimeSnapshotFacts",
        export: "CoreExport",
        key: str,
        now: "datetime",
    ) -> "RuntimeMembershipSnapshot":
        artifacts = {
            binding.configuration_id: (artifact, binding.revision)
            for artifact in export.artifacts
            for binding in artifact.configurations
        }
        memberships = []
        bindings = []
        for row in facts.profiles:
            artifact, revision = artifacts[row.configuration_id]
            credential = ClientCredentials.model_validate_json(
                decrypt(row.encrypted_credentials, key)
            )
            address = row.client_address
            if (
                row.provision_action == "revoke"
                and row.provision_payload is not None
            ):
                retired_target = ProvisionPayloadEncoding.decode(
                    row.provision_payload, key
                )
                credential, address = (
                    retired_target.credentials,
                    retired_target.client_address,
                )
            available = ServerProfileAvailability.eligible(
                services_available=row.services_enabled
                and not row.service_hold_pending,
                status=row.status,
                request_state=row.request_state,
                expires_at=row.expires_at,
                quota_bytes=row.quota_bytes,
                used_bytes=row.used_bytes,
                now=now,
            )
            policy = (
                FulfillmentPolicy.model_validate_json(row.request_policy_json)
                if row.request_policy_json
                else None
            )
            memberships.append(
                InstalledProfileMembership(
                    profile_id=row.id,
                    subscription_id=row.subscription_id,
                    generation=row.generation,
                    configuration_id=row.configuration_id,
                    configuration_revision=revision,
                    presence="present" if available else "absent",
                    credential_sha256=InstalledProfileEncoding.credential_digest(
                        ProvisionNodeSecrets.credentials(credential)
                    ),
                    client_address=address,
                    artifact_filename=artifact.filename,
                    artifact_sha256=artifact.sha256,
                )
            )
            bindings.append(
                RuntimeEntitlementBinding(
                    profile_id=row.id,
                    generation=row.generation,
                    quota_bytes=row.quota_bytes,
                    duration_days=row.duration_days,
                    expires_at=row.expires_at,
                    pending_activation=(
                        policy is not None
                        and policy.expiry_start == "activation"
                        and row.request_activated_at is None
                        and row.request_state == "dispatching"
                    ),
                )
            )
        return RuntimeMembershipSnapshot(
            memberships=memberships, bindings=bindings
        )

    @staticmethod
    def normalize_activation(
        facts: "RuntimeSnapshotFacts",
        snapshot: "RuntimeMembershipSnapshot",
        now: "datetime",
    ) -> "RuntimeSnapshotFacts":
        by_id = {binding.profile_id: binding for binding in snapshot.bindings}
        profiles = []
        for row in facts.profiles:
            binding = by_id.get(row.id)
            if binding is not None:
                if (
                    binding.generation != row.generation
                    or binding.quota_bytes != row.quota_bytes
                    or binding.duration_days != row.duration_days
                ):
                    raise ValueError("runtime_snapshot_stale")
                if (
                    binding.pending_activation
                    and row.request_activated_at is not None
                    and row.duration_days is not None
                    and row.expires_at is not None
                    and row.expires_at
                    == row.request_activated_at
                    + timedelta(days=row.duration_days)
                    and row.expires_at > now
                ):
                    row = replace(row, expires_at=binding.expires_at)
            profiles.append(row)
        return RuntimeSnapshotFacts(facts.configurations, tuple(profiles))
