from datetime import UTC, datetime
from typing import Literal

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import BaseModel, Field, field_validator, model_validator

CapabilityReason = Literal[
    "adapter_unavailable",
    "counter_adapter_unavailable",
    "strict_enforcement_unavailable",
    "runtime_ip_adapter_unavailable",
    "device_admission_unavailable",
    "engine_completion_unavailable",
    "protocol_matrix_not_reported",
    "binary_reference_unverified",
    "core_binary_unavailable",
    "capability_binary_unavailable",
    "capability_binary_invalid",
    "capability_binary_capacity",
    "capability_probe_timeout",
    "capability_binary_changed",
    "capability_output_capacity",
    "capability_probe_unavailable",
    "capability_version_unavailable",
    "sing_box_v2ray_api_build_unavailable",
]
CapabilityScope = Literal[
    "local_immutable_document_validation",
    "fresh_authorized_immutable_bundle_lifecycle",
    "live_exact_installed_membership_only",
    "merged_xray_scoped_cumulative_counters",
    "whole_merged_core_stop_with_poll_overrun",
    "no_strict_quota_or_expiry_guarantee",
    "source_ip_not_device_identity",
    "no_device_count_guarantee",
    "unresolved_grants_preserved",
    "export_or_binary_version_is_not_protocol_acceptance",
]


class NodeCapabilityCapacity(BaseModel):
    enabled: bool = False
    max_report_bytes: int = Field(gt=0)
    max_history_per_node: int = Field(gt=0)
    page_size: int = Field(gt=0)
    max_page_size: int = Field(gt=0)
    freshness_seconds: int = Field(gt=0)
    max_report_age_seconds: int = Field(gt=0)
    future_skew_seconds: int = Field(ge=0)

    @model_validator(mode="after")
    def paging_capacity(self) -> "NodeCapabilityCapacity":
        if self.page_size > self.max_page_size:
            raise ValueError("Capability page default exceeds maximum")
        return self


class ExecutableObservation(BaseDTO):
    available: bool
    version: str | None = Field(
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32
    )
    sha256: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    v2ray_api_build_tag: bool
    reason_code: CapabilityReason | None

    @model_validator(mode="after")
    def observation_fields(self) -> "ExecutableObservation":
        if self.available:
            if (
                self.version is None
                or self.sha256 is None
                or self.reason_code is not None
            ):
                raise ValueError(
                    "Available binary observation requires version and digest"
                )
        elif (
            self.version is not None
            or self.sha256 is not None
            or self.reason_code is None
            or self.v2ray_api_build_tag
        ):
            raise ValueError(
                "Unavailable binary cannot claim observed metadata"
            )
        return self


class OperationCapability(BaseDTO):
    implemented: bool
    compatibility: Literal["reference_match", "unverified", "unavailable"]
    scope: CapabilityScope
    reason_code: CapabilityReason | None

    @model_validator(mode="after")
    def compatibility_fields(self) -> "OperationCapability":
        if (self.compatibility == "reference_match") != (
            self.reason_code is None
        ):
            raise ValueError(
                "Compatibility requires an explicit reason or reference match"
            )
        if not self.implemented and self.compatibility != "unavailable":
            raise ValueError("Unimplemented operation cannot be compatible")
        return self


class AdapterCapability(BaseDTO):
    kind: Literal["xray", "sing_box", "openvpn", "wireguard", "hysteria"]
    adapter_revision: Literal[1]
    executable: ExecutableObservation
    validation: OperationCapability
    installation: OperationCapability
    installed_membership: OperationCapability
    counters: OperationCapability
    polled_stop: OperationCapability
    strict_quota_expiry: OperationCapability
    ip_admission: OperationCapability
    device_admission: OperationCapability
    final_counters: OperationCapability
    protocol_matrix: OperationCapability

    def require(
        self,
        operation: OperationCapability,
        scope: CapabilityScope,
        implemented: bool,
    ) -> None:
        if operation.scope != scope or operation.implemented != implemented:
            raise ValueError(
                "Capability does not match the declared adapter revision"
            )
        if (
            operation.compatibility == "reference_match"
            and not self.executable.available
        ):
            raise ValueError(
                "Reference match requires observed executable metadata"
            )

    @model_validator(mode="after")
    def adapter_operations(self) -> "AdapterCapability":
        installed = self.kind in ("xray", "sing_box")
        self.require(
            self.validation, "local_immutable_document_validation", installed
        )
        self.require(
            self.installation,
            "fresh_authorized_immutable_bundle_lifecycle",
            installed,
        )
        self.require(
            self.installed_membership,
            "live_exact_installed_membership_only",
            installed,
        )
        self.require(
            self.counters,
            "merged_xray_scoped_cumulative_counters",
            self.kind == "xray",
        )
        self.require(
            self.polled_stop,
            "whole_merged_core_stop_with_poll_overrun",
            self.kind == "xray",
        )
        self.require(
            self.strict_quota_expiry,
            "no_strict_quota_or_expiry_guarantee",
            False,
        )
        self.require(self.ip_admission, "source_ip_not_device_identity", False)
        self.require(self.device_admission, "no_device_count_guarantee", False)
        self.require(self.final_counters, "unresolved_grants_preserved", False)
        self.require(
            self.protocol_matrix,
            "export_or_binary_version_is_not_protocol_acceptance",
            False,
        )
        if not installed and self.executable.available:
            raise ValueError(
                "Unavailable adapter cannot claim executable observation"
            )
        return self


class NodeCapabilityReport(BaseDTO):
    schema_revision: Literal[1]
    observed_at: datetime
    adapters: list[AdapterCapability] = Field(min_length=5, max_length=5)

    @field_validator("observed_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Capability report time requires timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def complete_adapters(self) -> "NodeCapabilityReport":
        if {row.kind for row in self.adapters} != {
            "xray",
            "sing_box",
            "openvpn",
            "wireguard",
            "hysteria",
        }:
            raise ValueError(
                "Capability report requires each adapter exactly once"
            )
        return self


class NodeCapabilityReceived(BaseDTO):
    report_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    report: NodeCapabilityReport


class NodeCapabilitySearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
