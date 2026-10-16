"""Build recovery evidence from API-accepted window finality."""

from datetime import datetime, timedelta

from papilio.security.crypto import decrypt

from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.successor_encoding import (
    ManagedSuccessorEncoding,
)
from src.modules.network.managed_runtime.app.wire_encoding import (
    ManagedWireEncoding,
)
from src.modules.network.managed_runtime.domain.epoch_seals import (
    ManagedEpochSealLimits,
    ManagedEpochSealRead,
    ManagedEpochSealRecoveryCreate,
    ManagedEpochSealRecoveryReceipt,
    ManagedEpochSealRecoveryWindow,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedSnapshotReceiptWire,
)


class ManagedEpochSealRecoveryEncoding:
    @staticmethod
    def receipt(
        data: ManagedEpochSealRecoveryCreate,
        expectation: ManagedInstallationExpectation,
        startup_receipt_sha256: str,
        process_epoch: str,
        native: ManagedEpochSealRead,
        limits: ManagedEpochSealLimits,
        installed_closed_at: datetime,
        now: datetime,
        key: str,
    ) -> ManagedEpochSealRecoveryReceipt:
        if (
            len(native.windows) > limits.max_windows_per_epoch
            or len(native.grants) > limits.max_windows_per_epoch
            or len(native.barriers) > limits.max_windows_per_epoch
        ):
            raise ValueError("Recovery epoch evidence exceeds capacity")
        windows = {row.window_id: row for row in native.windows}
        grants = {row.id: row for row in native.grants}
        if (
            len(windows) != len(native.windows)
            or len(grants) != len(native.grants)
            or {row.grant_id for row in native.windows} != set(grants)
            or any(not row.is_closed for row in native.grants)
        ):
            raise ValueError(
                "Recovery requires closed grants for every window"
            )
        finality: dict[str, ManagedEpochSealRecoveryWindow] = {}
        barriers_seen: set[str] = set()
        for barrier in native.barriers:
            original = decrypt(barrier.encrypted_receipt, key).encode()
            receipt = ManagedSnapshotReceiptWire(
                epoch=process_epoch,
                barrier_id=barrier.barrier_id,
                snapshot_sha256=barrier.snapshot_sha256,
                bytes=len(original),
            )
            snapshot = ManagedWireEncoding.original_snapshot(
                original, receipt, expectation.capacity
            ).snapshot
            if (
                snapshot.installation != expectation.installation
                or snapshot.epoch != process_epoch
                or snapshot.adapter_revision != expectation.adapter_revision
                or snapshot.source_commit != expectation.source_commit
                or snapshot.frozen_at.replace(tzinfo=None)
                < installed_closed_at
                or snapshot.frozen_at
                > now + timedelta(seconds=expectation.clock_skew_seconds)
            ):
                raise ValueError("Recovery snapshot does not match its epoch")
            deltas = ManagedWireEncoding.grant_deltas(snapshot)
            for wire, delta in zip(snapshot.windows, deltas, strict=True):
                stored = windows.get(wire.window_id)
                grant = grants.get(delta.grant_id)
                if stored is None or grant is None:
                    raise ValueError(
                        "Recovery snapshot contains an unknown window"
                    )
                issued = ManagedSuccessorEncoding.output(stored, key).window
                if (
                    wire != issued
                    or wire.enforcement_mode != "strict_decoded"
                    or wire.enforcement_sha256
                    != expectation.enforcement_sha256
                    or wire.installation != expectation.installation
                    or wire.epoch != process_epoch
                    or snapshot.frozen_at < wire.issued_at
                    or grant.profile_id != stored.profile_id
                    or grant.subscription_id != stored.subscription_id
                    or grant.generation != stored.generation
                    or grant.configuration_revision
                    != wire.binding.configuration_revision
                    or grant.mode != "reserved"
                    or grant.process_epoch != process_epoch
                    or grant.allocated_bytes != stored.allocated_bytes
                    or grant.sequence != 1
                    or grant.upload_bytes != delta.upload_bytes
                    or grant.download_bytes != delta.download_bytes
                    or delta.window_id in finality
                ):
                    raise ValueError(
                        "Recovery finality conflicts with stored state"
                    )
                barriers_seen.add(barrier.barrier_id)
                finality[delta.window_id] = ManagedEpochSealRecoveryWindow(
                    window_id=delta.window_id,
                    grant_id=delta.grant_id,
                    window_sha256=stored.window_sha256,
                    barrier_id=barrier.barrier_id,
                    snapshot_sha256=barrier.snapshot_sha256,
                    upload_bytes=delta.upload_bytes,
                    download_bytes=delta.download_bytes,
                )
        if set(finality) != set(windows) or barriers_seen != {
            row.barrier_id for row in native.barriers
        }:
            raise ValueError("Recovery finality does not cover the epoch")
        result = ManagedEpochSealRecoveryReceipt(
            receipt_version=1,
            state="api_recovered_from_accepted_finality",
            epoch=process_epoch,
            request_id=data.request_id,
            startup_receipt_sha256=startup_receipt_sha256,
            windows=tuple(
                finality[window_id] for window_id in sorted(finality)
            ),
        )
        return result

    @staticmethod
    def request_digest(
        data: ManagedEpochSealRecoveryReceipt,
    ) -> str:
        payload = ManagedInstallationEncoding.compact(
            data.model_dump(mode="json"), canonical=True
        )
        return ManagedInstallationEncoding.digest(payload)
