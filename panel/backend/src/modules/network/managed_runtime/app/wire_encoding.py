"""Detached component conversion; async callers offload this computation."""

import hashlib
import json
from hmac import compare_digest

from src.modules.network.managed_runtime.domain.contracts import (
    ManagedRuntimeCapacity,
    ManagedWindow,
    Sha256,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedBindingWire,
    ManagedClosedStartupReceiptWire,
    ManagedClosedStartupWire,
    ManagedGrantDelta,
    ManagedInstallationWire,
    ManagedOriginalClosedStartup,
    ManagedOriginalSnapshot,
    ManagedSnapshotReceiptWire,
    ManagedSnapshotWire,
    ManagedWindowWire,
)


class ManagedWireEncoding:
    @staticmethod
    def original_closed_startup(
        payload: bytes | str,
        receipt: ManagedClosedStartupReceiptWire,
        capacity: ManagedRuntimeCapacity,
    ) -> ManagedOriginalClosedStartup:
        if isinstance(payload, str):
            payload = payload.encode()
        if not payload or len(payload) > capacity.max_snapshot_bytes:
            raise ValueError("Closed startup byte capacity exceeded")
        if receipt.bytes != len(payload) or not compare_digest(
            receipt.receipt_sha256, hashlib.sha256(payload).hexdigest()
        ):
            raise ValueError("Closed startup original digest mismatch")
        document = json.loads(
            payload,
            object_pairs_hook=ManagedWireEncoding.unique_object,
            parse_constant=ManagedWireEncoding.reject_constant,
        )
        startup = ManagedClosedStartupWire.model_validate(document)
        if startup.epoch != receipt.epoch or (
            len(startup.profiles) > capacity.max_profiles_per_barrier
        ):
            raise ValueError("Closed startup identity or capacity mismatch")
        return ManagedOriginalClosedStartup(
            original_bytes=payload, receipt=receipt, startup=startup
        )

    @staticmethod
    def window_bytes(window: ManagedWindowWire) -> bytes:
        document = window.model_dump(mode="json")
        if not window.enforcement_mode:
            document.pop("enforcement_mode")
        if not window.enforcement_sha256:
            document.pop("enforcement_sha256")
        # Go's explicit UTC6 fields follow the embedded plain struct.
        issued = document.pop("issued_at")
        until = document.pop("valid_until")
        document["issued_at"] = issued
        document["valid_until"] = until
        output = json.dumps(
            document, ensure_ascii=False, separators=(",", ":")
        )
        return (
            output.replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
            .encode()
        )

    @staticmethod
    def window(
        authority: ManagedWindow, *, enforcement_sha256: Sha256
    ) -> ManagedWindowWire:
        installation = authority.installation
        binding = authority.binding
        return ManagedWindowWire(
            enforcement_mode="strict_decoded",
            enforcement_sha256=enforcement_sha256,
            grant_id=authority.grant_id,
            window_id=authority.window_id,
            epoch=authority.epoch,
            installation=ManagedInstallationWire(
                materials_sha256=installation.materials_sha256,
                executable_sha256=installation.executable_sha256,
                document_sha256=installation.document_sha256,
                bindings_sha256=installation.bindings_sha256,
            ),
            binding=ManagedBindingWire(
                profile_id=binding.profile_id,
                generation=binding.generation,
                configuration_id=binding.configuration_id,
                configuration_revision=binding.configuration_revision,
                counter_identity=binding.counter_identity,
                inbound_tag=binding.inbound_tag,
            ),
            membership_sha256=authority.membership_sha256,
            profile_sha256=binding.profile_sha256,
            baseline_upload_bytes=authority.baseline_upload_bytes,
            baseline_download_bytes=authority.baseline_download_bytes,
            allocated_bytes=authority.allocated_bytes,
            issued_at=authority.issued_at,
            valid_until=authority.valid_until,
            predecessor=authority.predecessor,
        )

    @staticmethod
    def original_snapshot(
        payload: bytes,
        receipt: ManagedSnapshotReceiptWire,
        capacity: ManagedRuntimeCapacity,
    ) -> ManagedOriginalSnapshot:
        if not payload or len(payload) > capacity.max_snapshot_bytes:
            raise ValueError("Managed snapshot byte capacity exceeded")
        if receipt.bytes != len(payload) or not compare_digest(
            receipt.snapshot_sha256, hashlib.sha256(payload).hexdigest()
        ):
            raise ValueError("Managed original snapshot digest mismatch")
        document = json.loads(
            payload,
            object_pairs_hook=ManagedWireEncoding.unique_object,
            parse_constant=ManagedWireEncoding.reject_constant,
        )
        snapshot = ManagedSnapshotWire.model_validate(document)
        if (
            snapshot.epoch != receipt.epoch
            or snapshot.barrier_id != receipt.barrier_id
            or len(snapshot.profiles) > capacity.max_profiles_per_barrier
            or len(snapshot.windows) > capacity.max_windows_per_barrier
        ):
            raise ValueError("Managed snapshot identity or capacity mismatch")
        return ManagedOriginalSnapshot(
            original_bytes=payload, receipt=receipt, snapshot=snapshot
        )

    @staticmethod
    def grant_deltas(
        snapshot: ManagedSnapshotWire,
    ) -> tuple[ManagedGrantDelta, ...]:
        if not snapshot.windows:
            raise ValueError("Managed grant accounting requires windows")
        return tuple(
            ManagedGrantDelta(
                grant_id=window.grant_id,
                window_id=window.window_id,
                profile_id=window.binding.profile_id,
                upload_bytes=totals.upload_bytes
                - window.baseline_upload_bytes,
                download_bytes=totals.download_bytes
                - window.baseline_download_bytes,
            )
            for window, totals in zip(
                snapshot.windows, snapshot.profiles, strict=True
            )
        )

    @staticmethod
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate managed snapshot object key")
            result[key] = value
        return result

    @staticmethod
    def reject_constant(value: str) -> None:
        raise ValueError("Managed snapshot JSON constant is invalid")
