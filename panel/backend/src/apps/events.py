from faststream.nats import NatsBroker as NativeNatsBroker
from papilio.core.config import get_settings
from papilio_tasks.apps.events.application import create_app
from papilio_tasks.apps.events.registry.jetstream import JetRegistrar
from papilio_tasks.infra.faststream.brokers.backends.nats import NatsBroker

from src.config.providers import task_providers
from src.config.settings import PapilioSettings
from src.modules.billing.receipts.tasks.events import (
    ReceiptOcrConsumer,
    ReceiptOcrRequested,
)

settings = get_settings(PapilioSettings)
broker = NatsBroker(NativeNatsBroker(settings.events.nats_url))
registrar = JetRegistrar(broker)
registrar.publisher(ReceiptOcrRequested)
registrar.subscriber(ReceiptOcrConsumer)
app = create_app(registrar=registrar, providers=task_providers(settings))
