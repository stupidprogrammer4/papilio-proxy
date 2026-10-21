"""Compose execution readiness and process observations through their owner."""

from papilio_panel import __version__

from ..domain import Readiness, SystemStatus
from ..interfaces import ExecutionHealthStorage


class ExecutionHealth:
    def __init__(
        self, storage: ExecutionHealthStorage, environment: str, instance: str, brand_title: str
    ) -> None:
        self.storage = storage
        self.environment = environment
        self.instance = instance
        self.brand_title = brand_title

    def readiness(self) -> Readiness:
        facts = self.storage.readiness()
        return facts

    def status(self) -> SystemStatus:
        facts = self.storage.readiness()
        observations = self.storage.observations()
        return SystemStatus(
            version=__version__,
            brand_title=self.brand_title,
            environment=self.environment,
            instance=self.instance,
            database=facts.database,
            cache=facts.cache,
            workers_ready=facts.workers,
            workers=observations,
            available_modules=("system",),
        )

    def record(self, role: str, actual_queue: str) -> None:
        self.storage.record(role, actual_queue)
