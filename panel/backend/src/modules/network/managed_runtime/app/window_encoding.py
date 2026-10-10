"""Exact original window persistence; callers offload detached computation."""

from papilio.security.crypto import decrypt, encrypt

from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.wire_encoding import (
    ManagedWireEncoding,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
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
