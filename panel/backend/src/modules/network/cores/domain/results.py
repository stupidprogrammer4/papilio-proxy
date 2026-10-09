from dataclasses import dataclass

from src.modules.network.core_runtime.domain.dtos import RuntimeStatus
from src.modules.network.core_runtime.domain.models import (
    CoreRuntimeStateModel,
)
from src.modules.network.core_runtime.domain.results import (
    RuntimeObservationFields,
)
from src.modules.network.cores.domain.models import CoreModel


class CoreRuntimeSummary(RuntimeObservationFields):
    revision: int
    desired_revision_id: int | None
    applied_revision_id: int | None
    validated_revision_id: int | None
    observed_status: RuntimeStatus


@dataclass(frozen=True, slots=True)
class CoreInventoryFacts:
    core: CoreModel
    runtime: CoreRuntimeStateModel | None
