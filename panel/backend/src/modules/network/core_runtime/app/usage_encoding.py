import hashlib
import json
from typing import Any, Literal
from urllib.parse import urlsplit

from papilio.security.crypto import decrypt, encrypt

from src.modules.network.configurations.app.counter_identity import (
    profile_counter_identity,
)
from src.modules.network.configurations.app.server_json import (
    ServerJsonComposition,
)
from src.modules.network.configurations.domain.results import StoredSettings
from src.modules.network.core_runtime.domain.facts import RuntimeSnapshotFacts
from src.modules.network.core_runtime.domain.memberships import (
    RuntimeMembershipSnapshot,
)
from src.modules.network.core_runtime.domain.usage import (
    CoreUsageCapacity,
    RuntimeUsageArtifact,
    RuntimeUsageProfile,
    RuntimeUsageSnapshot,
)
from src.modules.network.cores.domain.exports import CoreArtifact, CoreExport
from src.modules.sales.catalog.domain.policies import QuotaPolicy


class RuntimeUsageEncoding:
    api_tag: Literal["papilio-stats-api"] = "papilio-stats-api"
    deny_tag = "papilio-stats-deny"

    @classmethod
    def decorate(
        cls,
        export: CoreExport,
        facts: RuntimeSnapshotFacts,
        policy: CoreUsageCapacity,
        key: str,
        protected_ports: list[int],
    ) -> CoreExport:
        port = policy.stats_ports.get(export.core_id)
        if policy.mode == "disabled" or port is None:
            return export
        if export.kind != "xray" or export.mode != "merged":
            raise ValueError("runtime_usage_kind_unavailable")
        if len(export.artifacts) != 1:
            raise ValueError("runtime_usage_artifact_unavailable")
        for configuration in facts.configurations:
            settings = StoredSettings.model_validate_json(
                decrypt(configuration.encrypted_settings, key)
            )
            if settings.server_json is not None and (
                settings.server_json.mode == "experimental"
            ):
                raise ValueError("runtime_usage_custom_document_unavailable")
        artifact = export.artifacts[0]
        document: dict[str, Any] = json.loads(
            artifact.content,
            object_pairs_hook=ServerJsonComposition.unique_object,
            parse_constant=ServerJsonComposition.reject_constant,
        )
        if set(document) - {
            "log",
            "inbounds",
            "outbounds",
            "routing",
            "dns",
            "policy",
        }:
            raise ValueError("runtime_usage_root_topology_unavailable")
        inbounds = document.get("inbounds")
        outbounds = document.get("outbounds")
        if not isinstance(inbounds, list) or not isinstance(outbounds, list):
            raise ValueError("runtime_usage_document_invalid")
        tags = [f"node-{item.id}" for item in facts.configurations]
        if {item.get("tag") for item in inbounds} != set(tags):
            raise ValueError("runtime_usage_custom_inbound_unavailable")
        for inbound in inbounds:
            if inbound.get("protocol") not in (
                "vless",
                "vmess",
                "trojan",
                "shadowsocks",
            ):
                raise ValueError("runtime_usage_ingress_unavailable")
            inbound_settings = inbound.get("settings", {})
            stream = inbound.get("streamSettings", {})
            if (
                not isinstance(inbound_settings, dict)
                or inbound_settings.get("fallbacks")
                or not isinstance(stream, dict)
                or set(stream)
                - {
                    "network",
                    "security",
                    "realitySettings",
                    "tlsSettings",
                    "wsSettings",
                    "grpcSettings",
                }
            ):
                raise ValueError("runtime_usage_ingress_unavailable")
            reality = stream.get("realitySettings", {})
            if not isinstance(reality, dict):
                raise ValueError("runtime_usage_ingress_unavailable")
            if "dest" in reality:
                try:
                    destination_port = urlsplit("//" + reality["dest"]).port
                except (ValueError, TypeError):
                    raise ValueError(
                        "runtime_usage_ingress_unavailable"
                    ) from None
                if destination_port in protected_ports:
                    raise ValueError("runtime_usage_reserved_destination")
        if any(
            item.get("tag") in (cls.api_tag, cls.deny_tag)
            for item in inbounds + outbounds
        ):
            raise ValueError("runtime_usage_reserved_tag_conflict")
        for outbound in outbounds:
            protocol = outbound.get("protocol")
            settings = outbound.get("settings", {})
            allowed = (
                {"domainStrategy"} if protocol == "freedom" else {"response"}
            )
            if (
                protocol not in ("freedom", "blackhole")
                or set(outbound) - {"tag", "protocol", "settings"}
                or not isinstance(settings, dict)
                or set(settings) - allowed
            ):
                raise ValueError("runtime_usage_egress_unavailable")
        if "api" in document or "stats" in document:
            raise ValueError("runtime_usage_reserved_document_conflict")
        routing = document.setdefault("routing", {})
        if not isinstance(routing, dict) or not isinstance(
            routing.get("rules", []), list
        ):
            raise ValueError("runtime_usage_routing_invalid")
        if routing.get("balancers"):
            raise ValueError("runtime_usage_custom_balancer_unavailable")
        if any(
            not isinstance(rule, dict)
            or rule.get("outboundTag") in (cls.api_tag, cls.deny_tag)
            or rule.get("balancerTag") is not None
            or not isinstance(rule.get("inboundTag", []), list)
            or cls.api_tag in rule.get("inboundTag", [])
            for rule in routing.get("rules", [])
        ):
            raise ValueError("runtime_usage_reserved_routing_conflict")
        protected = [
            {
                "type": "field",
                "inboundTag": [cls.api_tag],
                "outboundTag": cls.api_tag,
            },
            {
                "type": "field",
                "inboundTag": tags,
                "port": ",".join(str(item) for item in protected_ports),
                "outboundTag": cls.deny_tag,
            },
            {
                "type": "field",
                "inboundTag": tags,
                "ip": ["127.0.0.0/8", "::1/128"],
                "port": ",".join(str(item) for item in protected_ports),
                "outboundTag": cls.deny_tag,
            },
            {
                "type": "field",
                "inboundTag": tags,
                "domain": ["full:localhost"],
                "port": ",".join(str(item) for item in protected_ports),
                "outboundTag": cls.deny_tag,
            },
        ]
        routing["domainStrategy"] = "IPOnDemand"
        routing["rules"] = protected + routing.get("rules", [])
        inbounds.append(
            {
                "tag": cls.api_tag,
                "listen": "127.0.0.1",
                "port": port,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
            }
        )
        outbounds.append({"tag": cls.deny_tag, "protocol": "blackhole"})
        document["api"] = {"tag": cls.api_tag, "services": ["StatsService"]}
        document["stats"] = {}
        application_policy = document.setdefault("policy", {})
        if not isinstance(application_policy, dict):
            raise ValueError("runtime_usage_policy_invalid")
        levels = application_policy.setdefault("levels", {})
        if not isinstance(levels, dict):
            raise ValueError("runtime_usage_policy_invalid")
        level = levels.setdefault("0", {})
        if not isinstance(level, dict):
            raise ValueError("runtime_usage_policy_invalid")
        level["statsUserUplink"] = True
        level["statsUserDownlink"] = True
        content = json.dumps(
            document, ensure_ascii=False, allow_nan=False, indent=2
        )
        if len(content.encode()) > policy.max_document_bytes:
            raise ValueError("runtime_usage_document_capacity")
        return CoreExport(
            core_id=export.core_id,
            node_id=export.node_id,
            kind=export.kind,
            mode=export.mode,
            artifacts=[
                CoreArtifact(
                    filename=artifact.filename,
                    content=content,
                    media_type=artifact.media_type,
                    sha256=hashlib.sha256(content.encode()).hexdigest(),
                    configurations=artifact.configurations,
                )
            ],
        )

    @classmethod
    def capture(
        cls,
        export: CoreExport,
        members: RuntimeMembershipSnapshot,
        policy: CoreUsageCapacity,
        protected_ports: list[int],
        facts: RuntimeSnapshotFacts,
        default_quota_policy: QuotaPolicy,
    ) -> RuntimeUsageSnapshot | None:
        port = policy.stats_ports.get(export.core_id)
        if policy.mode == "disabled" or port is None:
            return None
        present = [
            item for item in members.memberships if item.presence == "present"
        ]
        if len(present) > policy.max_profiles:
            raise ValueError("runtime_usage_profile_capacity")
        artifact = export.artifacts[0]
        quota_policies = {
            row.id: (
                QuotaPolicy.model_validate_json(row.quota_policy_json)
                if row.quota_policy_json is not None
                else default_quota_policy
            )
            for row in facts.profiles
        }
        snapshot = RuntimeUsageSnapshot(
            mode=policy.mode,
            artifacts=[
                RuntimeUsageArtifact(
                    artifact_filename=artifact.filename,
                    artifact_sha256=artifact.sha256,
                    listen_address="127.0.0.1",
                    listen_port=port,
                    inbound_api_tag=cls.api_tag,
                    protected_ports=protected_ports,
                )
            ],
            profiles=[
                RuntimeUsageProfile(
                    profile_id=item.profile_id,
                    subscription_id=item.subscription_id,
                    generation=item.generation,
                    configuration_id=item.configuration_id,
                    configuration_revision=item.configuration_revision,
                    artifact_filename=item.artifact_filename,
                    artifact_sha256=item.artifact_sha256,
                    counter_identity=profile_counter_identity(
                        item.profile_id, item.generation
                    ),
                    grant_bytes=quota_policies[item.profile_id].grant_bytes,
                )
                for item in present
            ],
        )
        document = json.loads(artifact.content)
        for configuration in artifact.configurations:
            inbound = next(
                item
                for item in document["inbounds"]
                if item["tag"] == f"node-{configuration.configuration_id}"
            )
            clients = inbound.get("settings", {}).get("clients", [])
            expected = {
                item.counter_identity
                for item in snapshot.profiles
                if item.configuration_id == configuration.configuration_id
            }
            if {item.get("email") for item in clients} != expected or any(
                item.get("level") != 0 for item in clients
            ):
                raise ValueError("runtime_usage_client_provenance_invalid")
        return snapshot

    @staticmethod
    def digest(snapshot: RuntimeUsageSnapshot) -> str:
        value = json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def encode(snapshot: RuntimeUsageSnapshot, key: str) -> str:
        return encrypt(snapshot.model_dump_json(), key)

    @staticmethod
    def decode(value: str, key: str) -> RuntimeUsageSnapshot:
        return RuntimeUsageSnapshot.model_validate_json(decrypt(value, key))

    @staticmethod
    def compatible(
        snapshot: RuntimeUsageSnapshot | None,
        core_id: int,
        policy: CoreUsageCapacity | None,
        protected_ports: list[int],
    ) -> bool:
        enabled = (
            policy is not None
            and policy.mode != "disabled"
            and core_id in policy.stats_ports
        )
        if not enabled:
            return snapshot is None and not protected_ports
        assert policy is not None
        return (
            snapshot is not None
            and len(snapshot.artifacts) == 1
            and snapshot.artifacts[0].listen_port
            == policy.stats_ports[core_id]
            and snapshot.mode == policy.mode
            and snapshot.artifacts[0].protected_ports == protected_ports
        )
