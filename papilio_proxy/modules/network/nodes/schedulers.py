from typing import Any, ClassVar

from papilio_tasks.apps.schedulers import Scheduler

from papilio_proxy.modules.network.nodes.app.services import NodeReconciler


class NodeReconcileJob(Scheduler):
    schedule: ClassVar[list[dict[str, Any]] | None] = [{"interval": 2}]

    def __init__(self, reconciler: NodeReconciler | None) -> None:
        self._reconciler = reconciler

    async def run(self) -> None:
        if self._reconciler:
            await self._reconciler.run_once()
