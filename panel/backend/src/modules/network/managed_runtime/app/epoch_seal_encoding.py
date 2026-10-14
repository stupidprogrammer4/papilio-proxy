"""Detached exact seal validation against native, already settled finality."""

import json
from datetime import UTC, datetime, timedelta
from hmac import compare_digest

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
    ManagedEpochSealProfileRequest,
    ManagedEpochSealRead,
    ManagedEpochSealSubmission,
    ManagedEpochSealWire,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedSnapshotReceiptWire,
)


class ManagedEpochSealEncoding:
    @staticmethod
    def request_digest(data: ManagedEpochSealSubmission) -> str:
        payload = ManagedInstallationEncoding.compact(
            data.receipt.model_dump(mode="json"), canonical=True
        )
        return ManagedInstallationEncoding.digest(payload)

    @staticmethod
    def original_matches(data: ManagedEpochSealSubmission) -> bool:
        raw = data.original_receipt.encode()
        return len(raw) == data.receipt.bytes and compare_digest(
            ManagedInstallationEncoding.digest(raw),
            data.receipt.receipt_sha256,
        )

    @staticmethod
    def verify(
        data: ManagedEpochSealSubmission,
        expectation: ManagedInstallationExpectation,
        startup_sha256: str,
        process_epoch: str,
        native: ManagedEpochSealRead,
        limits: ManagedEpochSealLimits,
        now: datetime,
        installed_closed_at: datetime,
        key: str,
    ) -> ManagedEpochSealWire:
        raw = data.original_receipt.encode()
        if (
            len(raw) > limits.max_receipt_bytes
            or not ManagedEpochSealEncoding.original_matches(data)
            or data.receipt.epoch != process_epoch
        ):
            raise ValueError("Seal original digest, size or epoch mismatch")
        document = json.loads(
            raw,
            object_pairs_hook=ManagedWireEncoding.unique_object,
            parse_constant=ManagedWireEncoding.reject_constant,
        )
        seal = ManagedEpochSealWire.model_validate(document)
        members = tuple(
            ManagedEpochSealProfileRequest(
                binding=row.binding,
                membership_sha256=row.membership_sha256,
                profile_sha256=row.profile_sha256,
            )
            for row in expectation.profiles
        )
        if (
            seal.request.epoch != process_epoch
            or seal.request.request_id != data.receipt.request_id
            or seal.request.profiles != members
            or seal.installation != expectation.installation
            or seal.adapter_revision != expectation.adapter_revision
            or seal.source_commit != expectation.source_commit
            or seal.enforcement_sha256 != expectation.enforcement_sha256
            or seal.window_policy_sha256 != expectation.window_policy_sha256
            or seal.startup_receipt_sha256 != startup_sha256
            or seal.observed_at.astimezone(UTC)
            < installed_closed_at.replace(tzinfo=UTC)
            or seal.observed_at.astimezone(UTC)
            > now.astimezone(UTC)
            + timedelta(seconds=expectation.clock_skew_seconds)
            or len(native.windows) > limits.max_windows_per_epoch
            or len(native.grants) > limits.max_windows_per_epoch
            or len(native.barriers) > limits.max_windows_per_epoch
        ):
            raise ValueError(
                "Seal build, membership, time or capacity mismatch"
            )
        windows = {row.id: row for row in native.windows}
        grants = {row.id: row for row in native.grants}
        if (
            len(windows) != len(native.windows)
            or len(grants) != len(native.grants)
            or {row.grant_id for row in native.windows} != set(grants)
            or any(not row.is_closed for row in native.grants)
            or any(
                row.profile_id
                not in {item.binding.profile_id for item in members}
                for row in native.windows
            )
        ):
            raise ValueError(
                "Seal native epoch retains unresolved reservations"
            )
        # Every issued window needs its original accepted final snapshot, even
        # when the component receipt references only the final chain tip.
        finals = {}
        for barrier in native.barriers:
            original = decrypt(barrier.encrypted_receipt, key).encode()
            reference = ManagedSnapshotReceiptWire(
                epoch=process_epoch,
                barrier_id=barrier.barrier_id,
                snapshot_sha256=barrier.snapshot_sha256,
                bytes=len(original),
            )
            snapshot = ManagedWireEncoding.original_snapshot(
                original, reference, expectation.capacity
            ).snapshot
            if (
                snapshot.installation != expectation.installation
                or snapshot.epoch != process_epoch
                or snapshot.adapter_revision != expectation.adapter_revision
                or snapshot.source_commit != expectation.source_commit
            ):
                raise ValueError("Seal final snapshot build or epoch mismatch")
            for wire in snapshot.windows:
                if wire.window_id in finals:
                    raise ValueError("Duplicate finality for a sealed window")
                totals = next(
                    (
                        row
                        for row in snapshot.profiles
                        if row.binding == wire.binding
                    ),
                    None,
                )
                delta = next(
                    (
                        row
                        for row in ManagedWireEncoding.grant_deltas(snapshot)
                        if row.window_id == wire.window_id
                    ),
                    None,
                )
                if totals is None or delta is None:
                    raise ValueError("Seal final counters missing")
                finals[wire.window_id] = (wire, reference, totals, delta)
        if set(finals) != {row.window_id for row in native.windows}:
            raise ValueError(
                "Seal lacks exact native finality for every window"
            )
        for stored in native.windows:
            issued = ManagedSuccessorEncoding.output(stored, key)
            wire, _, _, delta = finals[stored.window_id]
            grant = grants[stored.grant_id]
            if (
                wire != issued.window
                or wire.enforcement_mode != "strict_decoded"
                or wire.enforcement_sha256 != expectation.enforcement_sha256
                or wire.installation != expectation.installation
                or wire.epoch != process_epoch
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
            ):
                raise ValueError(
                    "Seal native settled window or grant mismatch"
                )
        for profile in seal.profiles:
            chain = tuple(
                row
                for row in native.windows
                if row.profile_id == profile.binding.profile_id
            )
            tip = max(chain, key=lambda row: row.id) if chain else None
            if tip is None:
                if not profile.never_admitted:
                    raise ValueError(
                        "Seal claims admission without a native window"
                    )
                continue
            wire, reference, totals, _ = finals[tip.window_id]
            if (
                profile.never_admitted
                or profile.window != wire
                or profile.snapshot != reference
                or profile.totals != totals
                or seal.observed_at < wire.issued_at
            ):
                raise ValueError(
                    "Seal does not bind the exact settled chain tip"
                )
        return seal
