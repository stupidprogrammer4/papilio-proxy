"""Native bot schema upgrade preserves nonempty node data and schedule choices."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from papilio_panel.modules.nodes.domain import AgentRuntime, NodeCreate, NodeDefinition
from papilio_panel.modules.nodes.models import Node, NodeOperation, NodeOutbox
from papilio_panel.modules.nodes.providers import nodes

pytestmark = pytest.mark.django_db(transaction=True)


def test_bot_migration_retains_existing_node_and_disabled_delivery_schedule() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    previous = [target for target in latest if target[0] != "bots"] + [("bots", None)]
    executor.migrate(previous)
    try:
        owner = User.objects.create_superuser(
            username="prior-bot-owner", password="isolated-prior-password-744!"
        )
        created = nodes.create(
            NodeCreate(
                actor_id=owner.pk,
                request_key=uuid4(),
                definition=NodeDefinition(
                    name="prior-node",
                    endpoint_url="https://prior.example.invalid:9443",
                    runtime=AgentRuntime(request_timeout_seconds=19),
                ),
            )
        )
        interval, _ = IntervalSchedule.objects.get_or_create(every=17, period="seconds")
        schedule = PeriodicTask.objects.get(name__endswith=".node-outbox")
        schedule.enabled = False
        schedule.interval = interval
        schedule.save()
    finally:
        MigrationExecutor(connection).migrate(latest)
    node = Node.objects.get(pk=created.node.id)
    assert node.runtime.request_timeout_seconds == 19
    assert NodeOperation.objects.get(pk=created.operation.id).status == "queued"
    assert NodeOutbox.objects.get(operation_id=created.operation.id).dispatched_at is None
    schedule.refresh_from_db()
    assert not schedule.enabled and schedule.interval is not None
    assert schedule.interval.every == 17
