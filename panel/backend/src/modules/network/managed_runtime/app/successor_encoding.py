"""Detached exact-byte verification; parsing never establishes DB finality."""

import json
from hmac import compare_digest

from papilio.security.crypto import decrypt

from src.modules.network.managed_runtime.app.admission_encoding import (
    ManagedAdmissionEncoding,
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
from src.modules.network.managed_runtime.domain.admissions import (
    ManagedAdmissionReceipt,
    ManagedAdmissionSubmission,
)
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalOut,
)
from src.modules.network.managed_runtime.domain.contracts import (
    ManagedPredecessor,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.successors import (
    ManagedSuccessorAdmissionFacts,
    ManagedSuccessorBaseline,
    ManagedSuccessorEvidence,
    ManagedSuccessorWindowCreate,
    ManagedSuccessorWindowFacts,
    ManagedSuccessorWindowOut,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedSnapshotReceiptWire,
    ManagedWindowWire,
)


class ManagedSuccessorEncoding:
    @staticmethod
    def output(
        stored: ManagedSuccessorWindowFacts, key: str
    ) -> ManagedSuccessorWindowOut:
        original = decrypt(stored.encrypted_window, key)
        if not compare_digest(
            ManagedInstallationEncoding.digest(original.encode()),
            stored.window_sha256,
        ):
            raise ValueError("Successor persisted window digest mismatch")
        return ManagedSuccessorWindowOut(
            id=stored.id,
            window_sha256=stored.window_sha256,
            original_window=original,
            window=ManagedWindowWire.model_validate_json(original),
        )

    @staticmethod
    def evidence(
        stored: ManagedSuccessorWindowFacts,
        acceptance: ManagedPredecessor,
        encrypted_receipt: str,
        upload_bytes: int,
        download_bytes: int,
        key: str,
    ) -> ManagedSuccessorEvidence:
        window = ManagedSuccessorEncoding.output(stored, key)
        receipt = decrypt(encrypted_receipt, key).encode()
        return ManagedSuccessorEvidence(
            original_window=window.original_window.encode(),
            window_sha256=window.window_sha256,
            window=window.window,
            original_receipt=receipt,
            receipt=ManagedSnapshotReceiptWire(
                epoch=acceptance.epoch,
                barrier_id=acceptance.barrier_id,
                snapshot_sha256=acceptance.snapshot_sha256,
                bytes=len(receipt),
            ),
            finality=ManagedWindowFinalOut(
                window_id=stored.window_id,
                grant_id=stored.grant_id,
                acceptance=acceptance,
                upload_bytes=upload_bytes,
                download_bytes=download_bytes,
            ),
        )

    @staticmethod
    def verify_paid_root(
        initial: ManagedSuccessorWindowFacts,
        admission: ManagedSuccessorAdmissionFacts,
        expectation: ManagedInstallationExpectation,
        startup_sha256: str,
        key: str,
    ) -> None:
        detached = ManagedWindowModel.model_validate(initial.model_dump())
        original = ManagedWindowEncoding.output(detached, key)
        claim = original.provision_claim
        if (
            claim is None
            or original.window.window_id != initial.window_id
            or original.window.grant_id != initial.grant_id
            or original.window.binding.profile_id != initial.profile_id
            or original.window.binding.generation != initial.generation
            or original.window.predecessor is not None
            or claim.task_id != initial.provision_task_id
            or admission.provision_task_id != claim.task_id
            or admission.window_id != initial.id
            or admission.outcome != "applied"
        ):
            raise ValueError("Successor root paid acceptance mismatch")
        receipt = decrypt(admission.encrypted_receipt, key)
        ManagedAdmissionEncoding.verify(
            ManagedAdmissionSubmission(
                claim_token=claim.claim_token,
                original_receipt=receipt,
                receipt=ManagedAdmissionReceipt(
                    epoch=original.window.epoch,
                    window_id=initial.window_id,
                    receipt_sha256=admission.receipt_sha256,
                    bytes=len(receipt.encode()),
                ),
            ),
            detached,
            expectation,
            startup_sha256,
            key,
        )

    @staticmethod
    def request_digest(
        predecessor_window_id: str, data: ManagedSuccessorWindowCreate
    ) -> str:
        payload = ManagedInstallationEncoding.compact(
            {
                "predecessor_window_id": predecessor_window_id,
                "request": data.model_dump(mode="json"),
            },
            canonical=True,
        )
        return ManagedInstallationEncoding.digest(payload)

    @staticmethod
    def verify_predecessor(
        predecessor_window_id: str,
        data: ManagedSuccessorWindowCreate,
        evidence: ManagedSuccessorEvidence,
        expectation: ManagedInstallationExpectation,
    ) -> ManagedSuccessorBaseline:
        window = evidence.window
        if (
            not evidence.original_window
            or len(evidence.original_window)
            > expectation.capacity.max_window_bytes
            or not compare_digest(
                ManagedInstallationEncoding.digest(evidence.original_window),
                evidence.window_sha256,
            )
        ):
            raise ValueError("Predecessor original window digest mismatch")
        document = json.loads(
            evidence.original_window,
            object_pairs_hook=ManagedWireEncoding.unique_object,
            parse_constant=ManagedWireEncoding.reject_constant,
        )
        original_window = ManagedWindowWire.model_validate(document)
        if (
            original_window != window
            or window.window_id != predecessor_window_id
            or window.installation != expectation.installation
            or window.membership_sha256 != expectation.membership_sha256
            or window.enforcement_mode != "strict_decoded"
            or window.enforcement_sha256 != expectation.enforcement_sha256
        ):
            raise ValueError("Predecessor installation or window mismatch")
        member = next(
            (
                row
                for row in expectation.profiles
                if row.binding.profile_id == window.binding.profile_id
            ),
            None,
        )
        if (
            member is None
            or member.binding != window.binding
            or member.membership_sha256 != window.membership_sha256
            or member.profile_sha256 != window.profile_sha256
        ):
            raise ValueError("Predecessor profile binding mismatch")
        original = ManagedWireEncoding.original_snapshot(
            evidence.original_receipt, evidence.receipt, expectation.capacity
        )
        snapshot = original.snapshot
        accepted = evidence.finality
        predecessor = accepted.acceptance
        if (
            snapshot.windows != (window,)
            or snapshot.installation != expectation.installation
            or snapshot.epoch != window.epoch
            or snapshot.adapter_revision != expectation.adapter_revision
            or snapshot.source_commit != expectation.source_commit
            or snapshot.frozen_at < window.issued_at
            or not snapshot.enforcement
            or accepted.window_id != window.window_id
            or accepted.grant_id != window.grant_id
            or predecessor != data.acceptance
            or predecessor.epoch != window.epoch
            or predecessor.profile_id != window.binding.profile_id
            or predecessor.barrier_id != evidence.receipt.barrier_id
            or predecessor.snapshot_sha256 != evidence.receipt.snapshot_sha256
        ):
            raise ValueError("Predecessor accepted snapshot mismatch")
        delta = next(
            (
                item
                for item in ManagedWireEncoding.grant_deltas(snapshot)
                if item.window_id == window.window_id
                and item.profile_id == window.binding.profile_id
                and item.grant_id == window.grant_id
            ),
            None,
        )
        if (
            delta is None
            or accepted.upload_bytes != delta.upload_bytes
            or accepted.download_bytes != delta.download_bytes
        ):
            raise ValueError("Predecessor settled counters mismatch")
        totals = next(
            (
                item
                for item in snapshot.profiles
                if item.binding == window.binding
            ),
            None,
        )
        if totals is None:
            raise ValueError("Predecessor cumulative counters missing")
        return ManagedSuccessorBaseline(
            upload_bytes=totals.upload_bytes,
            download_bytes=totals.download_bytes,
            predecessor=predecessor,
        )
