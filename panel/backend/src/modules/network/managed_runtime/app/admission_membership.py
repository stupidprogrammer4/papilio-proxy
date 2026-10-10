"""Current native snapshot compatibility for a first managed admission."""

from datetime import datetime
from hmac import compare_digest

from src.modules.network.core_runtime.app.memberships import (
    InstalledProfileEncoding,
)
from src.modules.network.core_runtime.app.payloads import RuntimePayload
from src.modules.network.core_runtime.domain.facts import RuntimeSnapshotFacts


class ManagedAdmissionMembership:
    @staticmethod
    def verify(
        facts: RuntimeSnapshotFacts,
        encrypted_memberships: str,
        captured_membership_sha256: str,
        captured_snapshot_sha256: str,
        now: datetime,
        key: str,
    ) -> None:
        snapshot = InstalledProfileEncoding.decode(encrypted_memberships, key)
        if not compare_digest(
            InstalledProfileEncoding.membership_digest(snapshot),
            captured_membership_sha256,
        ):
            raise ValueError("Captured admission membership identity mismatch")
        normalized = InstalledProfileEncoding.normalize_activation(
            facts, snapshot, now
        )
        fingerprints = RuntimePayload.fingerprints(normalized, now)
        if not compare_digest(fingerprints[0], captured_snapshot_sha256):
            raise ValueError("Managed admission current snapshot changed")
