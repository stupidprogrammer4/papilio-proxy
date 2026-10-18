from papilio.core.config import get_settings
from papilio_tasks.apps.schedulers.redis import create_app
from taskiq import TaskiqEvents, TaskiqState

from src.apps.events import app as events_application
from src.config.providers import task_providers
from src.config.settings import PapilioSettings
from src.modules.operations.automation.tasks.schedulers.registrations import (
    ScanAutomationRegistrations,
)

settings = get_settings(PapilioSettings)
app = create_app(
    settings.tasks.scheduler,
    providers=task_providers(settings),
    modules=settings.app.modules,
    producers=(events_application,),
)
broker = app.broker
scheduler = app.scheduler

# Native worker lifecycle primes durable registrations after startup.


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def prime_automation_registrations(state: TaskiqState) -> None:
    await ScanAutomationRegistrations.enqueue()
