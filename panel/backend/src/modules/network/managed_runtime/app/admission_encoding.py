"""Detached validation of exact original strict admission evidence."""

import json

from papilio.security.crypto import secure_compare

from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
)
from src.modules.network.managed_runtime.app.wire_encoding import (
    ManagedWireEncoding,
)
from src.modules.network.managed_runtime.domain.admissions import (
    ManagedAdmissionSubmission,
    ManagedStrictAdmissionWire,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)


class ManagedAdmissionEncoding:
    @staticmethod
    def verify(
        data: ManagedAdmissionSubmission,
        window: ManagedWindowModel,
        expectation: ManagedInstallationExpectation,
        startup_sha256: str,
        key: str,
    ) -> ManagedStrictAdmissionWire:
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
            raise ValueError("Admission original byte identity mismatch")
        original = ManagedWindowEncoding.output(window, key)
        document = json.loads(
            payload,
            object_pairs_hook=ManagedWireEncoding.unique_object,
            parse_constant=ManagedWireEncoding.reject_constant,
        )
        admission = ManagedStrictAdmissionWire.model_validate(document)
        if (
            admission.window != original.window
            or admission.window_sha256 != window.window_sha256
            or receipt.window_id != window.window_id
            or receipt.epoch != original.window.epoch
            or admission.adapter_revision != expectation.adapter_revision
            or admission.source_commit != expectation.source_commit
            or admission.window_policy_sha256
            != expectation.window_policy_sha256
            or admission.startup_receipt_sha256 != startup_sha256
            or admission.window.installation != expectation.installation
            or admission.window.enforcement_mode != "strict_decoded"
            or admission.window.enforcement_sha256
            != expectation.enforcement_sha256
            or admission.observed_at.tzinfo is None
            or not original.window.issued_at
            <= admission.observed_at
            < original.window.valid_until
        ):
            raise ValueError(
                "Admission does not bind the issued strict window"
            )
        return admission
