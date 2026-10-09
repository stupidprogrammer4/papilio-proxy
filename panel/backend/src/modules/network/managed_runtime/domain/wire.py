"""Pinned component wire facts; parsing does not authorize admission."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_serializer, model_validator

from src.modules.network.managed_runtime.domain.contracts import (
    ByteCount,
    EpochIdentity,
    ImmutableContract,
    ManagedPredecessor,
    Sha256,
)


class ManagedInstallationWire(ImmutableContract):
    materials_sha256: Sha256
    executable_sha256: Sha256
    document_sha256: Sha256
    bindings_sha256: Sha256


class ManagedBindingWire(ImmutableContract):
    profile_id: int = Field(gt=0)
    generation: int = Field(ge=0)
    configuration_id: int = Field(gt=0)
    configuration_revision: int = Field(gt=0)
    counter_identity: str = Field(min_length=1)
    inbound_tag: str = Field(min_length=1)


class ManagedWindowWire(ImmutableContract):
    enforcement_mode: Literal["", "metadata_only", "strict_decoded"] = ""
    enforcement_sha256: str = ""
    grant_id: int = Field(gt=0)
    window_id: EpochIdentity
    epoch: EpochIdentity
    installation: ManagedInstallationWire
    binding: ManagedBindingWire
    membership_sha256: Sha256
    profile_sha256: Sha256
    baseline_upload_bytes: ByteCount
    baseline_download_bytes: ByteCount
    allocated_bytes: int = Field(gt=0, le=2**63 - 1)
    issued_at: datetime
    valid_until: datetime
    predecessor: ManagedPredecessor | None

    @field_serializer("issued_at", "valid_until")
    def utc6(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @model_validator(mode="after")
    def window_facts(self) -> "ManagedWindowWire":
        if self.issued_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("Window times require offsets")
        if self.valid_until <= self.issued_at:
            raise ValueError("Window validity must be positive")
        if (
            self.baseline_upload_bytes + self.baseline_download_bytes
            > 2**63 - 1
        ):
            raise ValueError("Window baseline exceeds signed counter range")
        if self.enforcement_mode == "strict_decoded":
            if len(self.enforcement_sha256) != 64 or any(
                character not in "0123456789abcdef"
                for character in self.enforcement_sha256
            ):
                raise ValueError("Strict window requires its policy digest")
        elif self.enforcement_sha256:
            raise ValueError("Metadata window cannot claim a strict digest")
        if self.predecessor is not None and (
            self.predecessor.epoch != self.epoch
            or self.predecessor.profile_id != self.binding.profile_id
        ):
            raise ValueError("Predecessor must belong to the same binding")
        return self


class ManagedTotalsWire(ImmutableContract):
    binding: ManagedBindingWire
    upload_bytes: ByteCount
    download_bytes: ByteCount
    unadmitted_upload_bytes: ByteCount = 0
    unadmitted_download_bytes: ByteCount = 0


class ManagedBudgetFinalWire(ImmutableContract):
    profile_id: int = Field(gt=0)
    window_id: EpochIdentity
    allocated_bytes: int = Field(gt=0, le=2**63 - 1)
    admitted_bytes: ByteCount
    closure_reason: Literal[
        "manual_freeze",
        "budget_exhausted",
        "window_expired",
        "reservation_contention",
    ]


class ManagedSnapshotWire(ImmutableContract):
    installation: ManagedInstallationWire
    epoch: EpochIdentity
    barrier_id: EpochIdentity
    adapter_revision: int = Field(gt=0)
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    accounting_scope: Literal["decoded_managed_tcp_payload_admission"]
    frozen_at: datetime
    profiles: tuple[ManagedTotalsWire, ...]
    windows: tuple[ManagedWindowWire, ...] = ()
    enforcement: tuple[ManagedBudgetFinalWire, ...] = ()

    @field_serializer("frozen_at")
    def utc6(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @model_validator(mode="after")
    def snapshot_facts(self) -> "ManagedSnapshotWire":
        if self.frozen_at.tzinfo is None:
            raise ValueError("Snapshot time requires an offset")
        if len({item.binding.profile_id for item in self.profiles}) != len(
            self.profiles
        ):
            raise ValueError("Snapshot profile identities must be unique")
        if len(
            {item.binding.counter_identity for item in self.profiles}
        ) != len(self.profiles):
            raise ValueError("Snapshot counter identities must be unique")
        if not self.windows:
            if self.enforcement:
                raise ValueError("Enforcement requires windows")
            return self
        if len(self.windows) != len(self.profiles):
            raise ValueError("Snapshot requires the exact window/profile set")
        if len({item.window_id for item in self.windows}) != len(self.windows):
            raise ValueError("Snapshot window identities must be unique")
        if len({item.grant_id for item in self.windows}) != len(self.windows):
            raise ValueError("Snapshot grant identities must be unique")
        for window, totals in zip(self.windows, self.profiles, strict=True):
            if (
                window.installation != self.installation
                or window.epoch != self.epoch
                or window.binding != totals.binding
                or totals.upload_bytes < window.baseline_upload_bytes
                or totals.download_bytes < window.baseline_download_bytes
            ):
                raise ValueError(
                    "Snapshot binding or cumulative baseline mismatch"
                )
        strict_count = sum(
            item.enforcement_mode == "strict_decoded" for item in self.windows
        )
        if strict_count != len(self.enforcement):
            raise ValueError("Snapshot strict evidence is incomplete")
        if self.enforcement:
            if len(self.enforcement) != len(self.windows):
                raise ValueError(
                    "Snapshot cannot mix strict and metadata windows"
                )
            for window, totals, final in zip(
                self.windows, self.profiles, self.enforcement, strict=True
            ):
                admitted = (
                    totals.upload_bytes
                    - window.baseline_upload_bytes
                    + totals.download_bytes
                    - window.baseline_download_bytes
                )
                if (
                    final.profile_id != window.binding.profile_id
                    or final.window_id != window.window_id
                    or final.allocated_bytes != window.allocated_bytes
                    or admitted != final.admitted_bytes
                    or admitted > 2**63 - 1
                    or admitted > final.allocated_bytes
                    or final.closure_reason == "budget_exhausted"
                    and admitted != final.allocated_bytes
                ):
                    raise ValueError(
                        "Snapshot admitted-byte evidence mismatch"
                    )
        return self


class ManagedSnapshotReceiptWire(ImmutableContract):
    epoch: EpochIdentity
    barrier_id: EpochIdentity
    snapshot_sha256: Sha256
    bytes: int = Field(gt=0)


class ManagedOriginalSnapshot(ImmutableContract):
    original_bytes: bytes
    receipt: ManagedSnapshotReceiptWire
    snapshot: ManagedSnapshotWire


class ManagedGrantDelta(ImmutableContract):
    grant_id: int = Field(gt=0)
    window_id: EpochIdentity
    profile_id: int = Field(gt=0)
    upload_bytes: ByteCount
    download_bytes: ByteCount

    @model_validator(mode="after")
    def signed_total(self) -> "ManagedGrantDelta":
        if self.upload_bytes + self.download_bytes > 2**63 - 1:
            raise ValueError("Grant delta exceeds signed accounting range")
        return self


class ManagedClosedProfileWire(ImmutableContract):
    binding: ManagedBindingWire
    membership_sha256: Sha256
    profile_sha256: Sha256
    phase: Literal["enrolled_closed"]
    active_operations: Literal[0]
    resources: Literal[0]
    upload_bytes: Literal[0]
    download_bytes: Literal[0]
    unadmitted_upload_bytes: Literal[0]
    unadmitted_download_bytes: Literal[0]


class ManagedClosedStartupWire(ImmutableContract):
    state: Literal["isolated_closed_startup_observation"]
    epoch: EpochIdentity
    installation: ManagedInstallationWire
    adapter_revision: int = Field(gt=0)
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    module: Literal["github.com/xtls/xray-core@v1.260327.0"]
    accounting_scope: Literal["decoded_managed_tcp_payload_admission"]
    accounting_mode: Literal["window_component"]
    enforcement_mode: Literal["strict_decoded"]
    enforcement_sha256: Sha256
    window_policy_sha256: Sha256
    profiles: tuple[ManagedClosedProfileWire, ...]
    api_authority: Literal[False]
    budget_enforced: Literal[False]
    deadline_enforced: Literal[False]
    historical_only: Literal[True]
    observed_at: datetime

    @model_validator(mode="after")
    def closed_profile_set(self) -> "ManagedClosedStartupWire":
        if self.observed_at.tzinfo is None:
            raise ValueError("Closed startup observation requires an offset")
        ids = tuple(item.binding.profile_id for item in self.profiles)
        if len(set(ids)) != len(ids) or ids != tuple(sorted(ids)):
            raise ValueError(
                "Closed startup profiles must be unique and sorted"
            )
        counters = {item.binding.counter_identity for item in self.profiles}
        if len(counters) != len(self.profiles):
            raise ValueError(
                "Closed startup counter identities must be unique"
            )
        return self


class ManagedClosedStartupReceiptWire(ImmutableContract):
    epoch: EpochIdentity
    receipt_sha256: Sha256
    bytes: int = Field(gt=0)


class ManagedOriginalClosedStartup(ImmutableContract):
    original_bytes: bytes
    receipt: ManagedClosedStartupReceiptWire
    startup: ManagedClosedStartupWire
