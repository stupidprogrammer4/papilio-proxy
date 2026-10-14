"""Exact original window persistence; callers offload detached computation."""

from papilio.security.crypto import decrypt, encrypt, hash_sha256

from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.wire_encoding import (
    ManagedWireEncoding,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedInitialWindowBatchDigest,
    ManagedWindowRequestDigest,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowCreate,
    ManagedInitialWindowOut,
    ManagedProvisionClaim,
)
from src.modules.network.managed_runtime.domain.wire import ManagedWindowWire


class ManagedWindowEncoding:
    @staticmethod
    def request_digest(id: int, data: ManagedInitialWindowCreate) -> str:
        return ManagedWindowEncoding._request_sha256(id, data)

    @staticmethod
    def request_digests(
        id: int, windows: tuple[ManagedInitialWindowCreate, ...]
    ) -> tuple[ManagedWindowRequestDigest, ...]:
        return tuple(
            ManagedWindowRequestDigest(
                profile_id=window.profile_id,
                generation=window.generation,
                request_key=window.request_key,
                request_sha256=ManagedWindowEncoding._request_sha256(
                    id, window
                ),
            )
            for window in windows
        )

    @staticmethod
    def batch_request_digest(
        id: int,
        batch_request_key: str,
        windows: tuple[ManagedInitialWindowCreate, ...],
    ) -> ManagedInitialWindowBatchDigest:
        digests = ManagedWindowEncoding.request_digests(id, windows)
        payload = ManagedInstallationEncoding.compact(
            {
                "installation_id": id,
                "batch_request_key": batch_request_key,
                "windows": [
                    window.model_dump(mode="json", exclude_none=True)
                    for window in windows
                ],
            },
            canonical=True,
        )
        return ManagedInitialWindowBatchDigest(
            request_sha256=ManagedInstallationEncoding.digest(payload),
            windows=digests,
        )

    @staticmethod
    def _request_sha256(id: int, data: ManagedInitialWindowCreate) -> str:
        return ManagedInstallationEncoding.digest(
            ManagedInstallationEncoding.compact(
                {
                    "installation_id": id,
                    "request": data.model_dump(mode="json", exclude_none=True),
                },
                canonical=True,
            )
        )

    @staticmethod
    def encode(window: ManagedWindowWire, key: str) -> tuple[str, str, int]:
        payload = ManagedWireEncoding.window_bytes(window)
        return (
            encrypt(payload.decode(), key),
            ManagedInstallationEncoding.digest(payload),
            len(payload),
        )

    @staticmethod
    def encode_many(
        windows: tuple[ManagedWindowWire, ...], key: str
    ) -> tuple[tuple[str, str, int], ...]:
        return tuple(
            ManagedWindowEncoding.encode(window, key) for window in windows
        )

    @staticmethod
    def encode_claims(
        claims: tuple[str | None, ...], key: str
    ) -> tuple[str | None, ...]:
        return tuple(
            encrypt(claim, key) if claim is not None else None
            for claim in claims
        )

    @staticmethod
    def hash_claim_tokens(
        claim_tokens: tuple[str | None, ...],
    ) -> tuple[str | None, ...]:
        return tuple(
            hash_sha256(token) if token is not None else None
            for token in claim_tokens
        )

    @staticmethod
    def outputs(
        rows: tuple[ManagedWindowModel, ...], key: str
    ) -> tuple[ManagedInitialWindowOut, ...]:
        return tuple(ManagedWindowEncoding.output(row, key) for row in rows)

    @staticmethod
    def output(row: ManagedWindowModel, key: str) -> ManagedInitialWindowOut:
        original = decrypt(row.encrypted_window, key)
        if (
            ManagedInstallationEncoding.digest(original.encode())
            != row.window_sha256
        ):
            raise ValueError("Managed persisted window digest mismatch")
        return ManagedInitialWindowOut(
            id=row.id,
            window_sha256=row.window_sha256,
            original_window=original,
            window=ManagedWindowWire.model_validate_json(original),
            provision_claim=ManagedProvisionClaim.model_validate_json(
                decrypt(row.encrypted_provision_claim, key)
            )
            if row.encrypted_provision_claim
            else None,
        )
