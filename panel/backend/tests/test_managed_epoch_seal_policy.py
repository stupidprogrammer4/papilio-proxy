import pytest
from pydantic import ValidationError

from src.modules.network.managed_runtime.domain.contracts import (
    ManagedRuntimeCapacity,
)
from src.modules.network.managed_runtime.domain.epoch_seals import (
    ManagedEpochSealLimits,
    ManagedEpochSealPolicy,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedAdapterPolicy,
)


def test_managed_adapter_defaults_epoch_sealing_to_disabled():
    policy = ManagedAdapterPolicy(
        source_commit="d2758a023cd7f4174a5a5fa4ff66e487d4342ba0",
        executable_sha256="a" * 64,
        materials_sha256="b" * 64,
        enforcement_sha256="c" * 64,
        window_policy_sha256="d" * 64,
        capacity=ManagedRuntimeCapacity(
            max_manifest_bytes=1,
            max_window_bytes=1,
            max_snapshot_bytes=1,
            max_profiles_per_barrier=1,
            max_windows_per_barrier=1,
            max_pending_epochs=1,
            max_retained_receipts=1,
            max_validity_ms=1,
            operation_timeout_ms=1,
            scan_batch_size=1,
            retry_seconds=1,
            max_attempts=1,
        ),
        claim_seconds=1,
        observation_seconds=1,
        clock_skew_seconds=0,
    )

    assert policy.epoch_seal_policy == ManagedEpochSealPolicy()


def test_strict_epoch_sealing_requires_explicit_capacity_limits():
    with pytest.raises(ValidationError):
        ManagedEpochSealPolicy(mode="strict")

    policy = ManagedEpochSealPolicy(
        mode="strict",
        limits=ManagedEpochSealLimits(
            max_windows_per_epoch=8,
            max_receipt_bytes=65536,
            max_epochs=2,
        ),
    )

    assert policy.limits is not None
    assert policy.limits.max_epochs == 2


def test_epoch_count_limit_must_be_positive():
    with pytest.raises(ValidationError):
        ManagedEpochSealLimits(
            max_windows_per_epoch=8,
            max_receipt_bytes=65536,
            max_epochs=0,
        )
