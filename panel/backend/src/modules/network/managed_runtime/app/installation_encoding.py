"""Detached immutable native export and CLOSED expectation derivation."""

import hashlib
import json

from papilio.security.crypto import decrypt, encrypt

from src.modules.network.configurations.app.counter_identity import (
    profile_counter_identity,
)
from src.modules.network.core_runtime.app.memberships import (
    InstalledProfileEncoding,
)
from src.modules.network.core_runtime.app.payloads import RuntimePayload
from src.modules.network.managed_runtime.domain.installations import (
    ManagedAdapterPolicy,
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedBindingWire,
    ManagedClosedProfileWire,
    ManagedClosedStartupReceiptWire,
    ManagedInstallationWire,
)


class ManagedInstallationEncoding:
    @staticmethod
    def acknowledgement_digest(
        token: str, original: str, receipt: ManagedClosedStartupReceiptWire
    ) -> str:
        return ManagedInstallationEncoding.digest(
            ManagedInstallationEncoding.compact(
                {
                    "claim_token": token,
                    "original_receipt": original,
                    "receipt": receipt.model_dump(mode="json"),
                }
            )
        )

    @staticmethod
    def compact(value: object, *, canonical: bool = False) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=canonical,
            separators=(",", ":"),
        ).encode()

    @staticmethod
    def digest(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def derive(
        revision_id: int,
        state_revision: int,
        encrypted_payload: str,
        encrypted_memberships: str,
        membership_sha256: str,
        policy: ManagedAdapterPolicy,
        key: str,
    ) -> ManagedInstallationExpectation:
        export = RuntimePayload.decode(encrypted_payload, key)
        snapshot = InstalledProfileEncoding.decode(encrypted_memberships, key)
        if (
            export.kind != "xray"
            or export.mode != "merged"
            or len(export.artifacts) != 1
        ):
            raise ValueError("managed_native_artifact_unsupported")
        artifact = export.artifacts[0]
        payload = artifact.content.encode()
        if (
            len(payload) > policy.capacity.max_manifest_bytes
            or ManagedInstallationEncoding.digest(payload) != artifact.sha256
            or InstalledProfileEncoding.membership_digest(snapshot)
            != membership_sha256
        ):
            raise ValueError("managed_native_artifact_invalid")
        document = json.loads(payload)
        members = sorted(snapshot.memberships, key=lambda row: row.profile_id)
        if len(members) > policy.capacity.max_profiles_per_barrier:
            raise ValueError("managed_native_membership_capacity")
        profiles = []
        bindings = []
        for member in members:
            if (
                member.presence != "present"
                or member.artifact_filename != artifact.filename
                or member.artifact_sha256 != artifact.sha256
            ):
                raise ValueError("managed_native_membership_unsupported")
            counter = profile_counter_identity(
                member.profile_id, member.generation
            )
            inbounds = [
                item
                for item in document["inbounds"]
                if item["tag"] == "node-" + str(member.configuration_id)
            ]
            if len(inbounds) != 1:
                raise ValueError("managed_native_binding_invalid")
            inbound = inbounds[0]
            clients = [
                item
                for item in inbound["settings"]["clients"]
                if item.get("email") == counter
            ]
            if (
                len(clients) != 1
                or clients[0].get("flow")
                or inbound["protocol"] != "vless"
            ):
                raise ValueError("managed_native_client_unsupported")
            binding = ManagedBindingWire(
                profile_id=member.profile_id,
                generation=member.generation,
                configuration_id=member.configuration_id,
                configuration_revision=member.configuration_revision,
                counter_identity=counter,
                inbound_tag=inbound["tag"],
            )
            bindings.append(binding.model_dump(mode="json"))
            profiles.append(
                ManagedClosedProfileWire(
                    binding=binding,
                    membership_sha256=membership_sha256,
                    profile_sha256=ManagedInstallationEncoding.digest(
                        ManagedInstallationEncoding.compact(
                            member.model_dump(mode="json"), canonical=True
                        )
                    ),
                    phase="enrolled_closed",
                    active_operations=0,
                    resources=0,
                    upload_bytes=0,
                    download_bytes=0,
                    unadmitted_upload_bytes=0,
                    unadmitted_download_bytes=0,
                )
            )
        return ManagedInstallationExpectation(
            runtime_revision_id=revision_id,
            runtime_state_revision=state_revision,
            claim_seconds=policy.claim_seconds,
            observation_seconds=policy.observation_seconds,
            clock_skew_seconds=policy.clock_skew_seconds,
            capacity=policy.capacity,
            artifact_filename=artifact.filename,
            artifact_sha256=artifact.sha256,
            membership_sha256=membership_sha256,
            installation=ManagedInstallationWire(
                materials_sha256=policy.materials_sha256,
                executable_sha256=policy.executable_sha256,
                document_sha256=ManagedInstallationEncoding.digest(
                    payload.strip()
                ),
                bindings_sha256=ManagedInstallationEncoding.digest(
                    ManagedInstallationEncoding.compact(bindings)
                ),
            ),
            adapter_revision=policy.adapter_revision,
            source_commit=policy.source_commit,
            enforcement_sha256=policy.enforcement_sha256,
            window_policy_sha256=policy.window_policy_sha256,
            profiles=tuple(profiles),
        )

    @staticmethod
    def encode(
        expectation: ManagedInstallationExpectation, key: str
    ) -> tuple[str, str]:
        payload = expectation.model_dump_json()
        return encrypt(payload, key), ManagedInstallationEncoding.digest(
            payload.encode()
        )

    @staticmethod
    def decode(payload: str, key: str) -> ManagedInstallationExpectation:
        return ManagedInstallationExpectation.model_validate_json(
            decrypt(payload, key)
        )
