"""Explicit identities for managed-runtime batch reads."""

from dataclasses import dataclass

from src.modules.network.managed_runtime.domain.contracts import Sha256
from src.modules.network.managed_runtime.domain.wire import (
    ManagedGrantDelta,
    ManagedOriginalSnapshot,
)


@dataclass(frozen=True, slots=True)
class ManagedWindowRequestIdentity:
    profile_id: int
    generation: int
    request_key: str


@dataclass(frozen=True, slots=True)
class ManagedBarrierIdentity:
    epoch_id: int
    barrier_id: str


@dataclass(frozen=True, slots=True)
class ManagedWindowRequestDigest:
    profile_id: int
    generation: int
    request_key: str
    request_sha256: Sha256


@dataclass(frozen=True, slots=True)
class ManagedInitialWindowBatchDigest:
    request_sha256: Sha256
    windows: tuple[ManagedWindowRequestDigest, ...]


@dataclass(frozen=True, slots=True)
class ManagedFinalityWindowComputation:
    window_id: str
    request_key: str
    request_sha256: Sha256
    original_snapshot: ManagedOriginalSnapshot
    grant_delta: ManagedGrantDelta


@dataclass(frozen=True, slots=True)
class ManagedEncryptedReceipt:
    window_id: str
    encrypted_receipt: str


@dataclass(frozen=True, slots=True)
class ManagedFinalityBatchComputation:
    request_sha256: Sha256
    windows: tuple[ManagedFinalityWindowComputation, ...]
