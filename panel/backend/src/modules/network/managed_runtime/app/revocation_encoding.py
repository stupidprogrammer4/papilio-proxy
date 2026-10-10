"""Detached exact revocation and accepted final snapshot verification."""

import json

from papilio.security.crypto import decrypt, secure_compare

from src.modules.network.managed_runtime.app.finality_encoding import (
    ManagedFinalityEncoding,
)
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
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
    ManagedBarrierModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.revocations import (
    ManagedRevocationSubmission,
    ManagedWindowRevocationWire,
)


class ManagedRevocationEncoding:
    @staticmethod
    def verify_original(
        data: ManagedRevocationSubmission,
        window: ManagedWindowModel,
        expectation: ManagedInstallationExpectation,
        startup_sha256: str,
        key: str,
    ) -> ManagedWindowRevocationWire:
        payload = data.original_receipt.encode()
        receipt = data.receipt
        if (
            len(payload) > expectation.capacity.max_snapshot_bytes
            or len(payload) != receipt.bytes
            or not secure_compare(
                ManagedInstallationEncoding.digest(payload),
                receipt.receipt_sha256,
            )
        ):
            raise ValueError("Revocation original byte identity mismatch")
        original = ManagedWindowEncoding.output(window, key)
        document = json.loads(
            payload,
            object_pairs_hook=ManagedWireEncoding.unique_object,
            parse_constant=ManagedWireEncoding.reject_constant,
        )
        revocation = ManagedWindowRevocationWire.model_validate(document)
        request = revocation.request
        if (
            revocation.window != original.window
            or receipt.epoch != original.window.epoch
            or receipt.request_id != request.request_id
            or receipt.profile_id != window.profile_id
            or request.epoch != original.window.epoch
            or request.window_id != window.window_id
            or request.binding != original.window.binding
            or revocation.installation != expectation.installation
            or revocation.adapter_revision != expectation.adapter_revision
            or revocation.source_commit != expectation.source_commit
            or revocation.startup_receipt_sha256 != startup_sha256
            or revocation.window_policy_sha256
            != expectation.window_policy_sha256
            or original.window.enforcement_mode != "strict_decoded"
            or original.window.enforcement_sha256
            != expectation.enforcement_sha256
            or revocation.snapshot.epoch != original.window.epoch
            or revocation.observed_at.tzinfo is None
            or revocation.observed_at < original.window.issued_at
        ):
            raise ValueError("Revocation does not bind the issued window")
        return revocation

    @staticmethod
    def verify_finality(
        revocation: ManagedWindowRevocationWire,
        window: ManagedWindowModel,
        barrier: ManagedBarrierModel,
        expectation: ManagedInstallationExpectation,
        key: str,
    ) -> None:
        receipt = revocation.snapshot
        if (
            barrier.barrier_id != receipt.barrier_id
            or barrier.snapshot_sha256 != receipt.snapshot_sha256
        ):
            raise ValueError("Revocation final snapshot was not accepted")
        snapshot = ManagedFinalityEncoding.verify(
            ManagedWindowFinalSubmission(
                original_receipt=decrypt(barrier.encrypted_receipt, key),
                receipt=receipt,
            ),
            window,
            expectation,
            revocation.request.epoch,
            key,
        )
        if revocation.observed_at < snapshot.snapshot.frozen_at:
            raise ValueError("Revocation precedes its final snapshot")
