"""Detached validation of exact original strict admission evidence."""

import json
from dataclasses import dataclass

from papilio.security.crypto import encrypt, hash_sha256, secure_compare

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
    ManagedAdmissionBatchCreate,
    ManagedAdmissionSubmission,
    ManagedStrictAdmissionWire,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedAdmissionBatchDigest,
    ManagedAdmissionWindowDigest,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedProvisionClaim,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedWindowWire,
)


@dataclass(frozen=True, slots=True)
class ManagedAdmissionPreparedItem:
    window_id: str
    admission: ManagedStrictAdmissionWire
    original_window: ManagedWindowWire
    provision_claim: ManagedProvisionClaim
    encrypted_receipt: str
    claim_hash: str


class ManagedAdmissionEncoding:
    @staticmethod
    def prepare_many(
        data: ManagedAdmissionBatchCreate,
        windows: tuple[ManagedWindowModel, ...],
        expectation: ManagedInstallationExpectation,
        startup_sha256: str,
        key: str,
    ) -> tuple[ManagedAdmissionPreparedItem, ...]:
        rows_by_id = {window.window_id: window for window in windows}
        prepared = []
        for item in data.windows:
            window = rows_by_id[item.window_id]
            original = ManagedWindowEncoding.output(window, key)
            admission = ManagedAdmissionEncoding.verify(
                item.submission,
                window,
                expectation,
                startup_sha256,
                key,
            )
            claim = original.provision_claim
            if (
                claim is None
                or claim.task_id != window.provision_task_id
                or not secure_compare(
                    claim.claim_token, item.submission.claim_token
                )
            ):
                raise ValueError("Managed provision claim does not match")
            prepared.append(
                ManagedAdmissionPreparedItem(
                    window_id=window.window_id,
                    admission=admission,
                    original_window=original.window,
                    provision_claim=claim,
                    encrypted_receipt=encrypt(
                        item.submission.original_receipt, key
                    ),
                    claim_hash=hash_sha256(claim.claim_token),
                )
            )
        return tuple(prepared)

    @staticmethod
    def batch_request_digest(
        installation_id: int, data: ManagedAdmissionBatchCreate
    ) -> ManagedAdmissionBatchDigest:
        payload = ManagedInstallationEncoding.compact(
            {
                "installation_id": installation_id,
                "batch_request_key": data.batch_request_key,
                "windows": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in data.windows
                ],
            },
            canonical=True,
        )
        windows = tuple(
            ManagedAdmissionWindowDigest(
                window_id=item.window_id,
                receipt_sha256=item.submission.receipt.receipt_sha256,
            )
            for item in data.windows
        )
        return ManagedAdmissionBatchDigest(
            request_sha256=ManagedInstallationEncoding.digest(payload),
            windows=windows,
        )

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
