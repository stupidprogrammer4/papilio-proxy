"""Run bounded managed-window batch encoding outside the API event loop."""

import anyio

from src.modules.network.managed_runtime.app.finality_encoding import (
    ManagedFinalityEncoding,
)
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
)
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalBatchCreate,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedFinalityBatchComputation,
    ManagedInitialWindowBatchDigest,
)
from src.modules.network.managed_runtime.domain.windows import (
    ManagedInitialWindowCreate,
)


async def compute_managed_window_batch_digest(
    installation_id: int,
    batch_request_key: str,
    windows: tuple[ManagedInitialWindowCreate, ...],
) -> ManagedInitialWindowBatchDigest:
    result = await anyio.to_thread.run_sync(
        ManagedWindowEncoding.batch_request_digest,
        installation_id,
        batch_request_key,
        windows,
    )
    return result


async def compute_managed_finality_batch(
    data: ManagedWindowFinalBatchCreate,
    windows: tuple[ManagedWindowModel, ...],
    expectation: ManagedInstallationExpectation,
    process_epoch: str,
    key: str,
) -> ManagedFinalityBatchComputation:
    result = await anyio.to_thread.run_sync(
        _compute_managed_finality_batch,
        data,
        windows,
        expectation,
        process_epoch,
        key,
    )
    return result


def _compute_managed_finality_batch(
    data: ManagedWindowFinalBatchCreate,
    windows: tuple[ManagedWindowModel, ...],
    expectation: ManagedInstallationExpectation,
    process_epoch: str,
    key: str,
) -> ManagedFinalityBatchComputation:
    original_snapshot = ManagedFinalityEncoding.verify_many(
        data, windows, expectation, process_epoch, key
    )
    request_sha256 = ManagedFinalityEncoding.batch_request_digest(data)
    return ManagedFinalityBatchComputation(request_sha256, original_snapshot)
