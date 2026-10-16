"""Offload bounded admission receipt validation and cryptography."""

from datetime import datetime

import anyio

from src.modules.network.core_runtime.domain.facts import RuntimeSnapshotFacts
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeRevisionModel,
)
from src.modules.network.managed_runtime.app.admission_encoding import (
    ManagedAdmissionEncoding,
    ManagedAdmissionPreparedItem,
)
from src.modules.network.managed_runtime.app.admission_membership import (
    ManagedAdmissionMembership,
)
from src.modules.network.managed_runtime.domain.admissions import (
    ManagedAdmissionBatchCreate,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedAdmissionBatchDigest,
)


async def compute_managed_admission_batch_digest(
    installation_id: int, data: ManagedAdmissionBatchCreate
) -> ManagedAdmissionBatchDigest:
    result = await anyio.to_thread.run_sync(
        ManagedAdmissionEncoding.batch_request_digest,
        installation_id,
        data,
    )
    return result


async def prepare_managed_admission_batch(
    data: ManagedAdmissionBatchCreate,
    windows: tuple[ManagedWindowModel, ...],
    expectation: ManagedInstallationExpectation,
    startup_sha256: str,
    revision: CoreRuntimeRevisionModel,
    snapshot: RuntimeSnapshotFacts,
    now: datetime,
    key: str,
) -> tuple[ManagedAdmissionPreparedItem, ...]:
    result = await anyio.to_thread.run_sync(
        _prepare_managed_admission_batch,
        data,
        windows,
        expectation,
        startup_sha256,
        revision,
        snapshot,
        now,
        key,
    )
    return result


def _prepare_managed_admission_batch(
    data: ManagedAdmissionBatchCreate,
    windows: tuple[ManagedWindowModel, ...],
    expectation: ManagedInstallationExpectation,
    startup_sha256: str,
    revision: CoreRuntimeRevisionModel,
    snapshot: RuntimeSnapshotFacts,
    now: datetime,
    key: str,
) -> tuple[ManagedAdmissionPreparedItem, ...]:
    if (
        revision.encrypted_memberships is None
        or revision.membership_sha256 is None
    ):
        raise ValueError("Managed runtime snapshot is incomplete")
    ManagedAdmissionMembership.verify(
        snapshot,
        revision.encrypted_memberships,
        revision.membership_sha256,
        revision.snapshot_sha256,
        now,
        key,
    )
    return ManagedAdmissionEncoding.prepare_many(
        data,
        windows,
        expectation,
        startup_sha256,
        key,
    )
