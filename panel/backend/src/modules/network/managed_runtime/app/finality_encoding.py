"""Detached original-byte and immutable-window verification."""

from papilio.security.crypto import decrypt

from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.wire_encoding import (
    ManagedWireEncoding,
)
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalSubmission,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedOriginalSnapshot,
    ManagedWindowWire,
)


class ManagedFinalityEncoding:
    @staticmethod
    def verify(
        data: ManagedWindowFinalSubmission,
        stored: ManagedWindowModel,
        expectation: ManagedInstallationExpectation,
        process_epoch: str,
        key: str,
    ) -> ManagedOriginalSnapshot:
        original_window = decrypt(stored.encrypted_window, key)
        wire = ManagedWindowWire.model_validate_json(original_window)
        if (
            ManagedInstallationEncoding.digest(original_window.encode())
            != stored.window_sha256
            or wire.window_id != stored.window_id
            or wire.grant_id != stored.grant_id
            or wire.epoch != process_epoch
            or wire.binding.profile_id != stored.profile_id
            or wire.binding.generation != stored.generation
            or wire.allocated_bytes != stored.allocated_bytes
            or wire.baseline_upload_bytes != stored.baseline_upload_bytes
            or wire.baseline_download_bytes != stored.baseline_download_bytes
            or wire.issued_at.replace(tzinfo=None) != stored.issued_at
            or wire.valid_until.replace(tzinfo=None) != stored.valid_until
            or wire.installation != expectation.installation
            or wire.membership_sha256 != expectation.membership_sha256
            or wire.enforcement_mode != "strict_decoded"
            or wire.enforcement_sha256 != expectation.enforcement_sha256
        ):
            raise ValueError("Stored managed window identity mismatch")
        snapshot = ManagedWireEncoding.original_snapshot(
            data.original_receipt.encode(), data.receipt, expectation.capacity
        )
        facts = snapshot.snapshot
        if (
            facts.windows != (wire,)
            or facts.installation != expectation.installation
            or facts.epoch != process_epoch
            or facts.adapter_revision != expectation.adapter_revision
            or facts.source_commit != expectation.source_commit
            or not facts.enforcement
        ):
            raise ValueError("Finality requires the exact strict window")
        return snapshot

    @staticmethod
    def request_digest(data: ManagedWindowFinalSubmission) -> str:
        payload = ManagedInstallationEncoding.compact(
            data.model_dump(mode="json"), canonical=True
        )
        return ManagedInstallationEncoding.digest(payload)
