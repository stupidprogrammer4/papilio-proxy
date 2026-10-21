"""Upgrade nonempty foundation schema through the native node migration."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from papilio_panel.modules.jobs.domain import TaskName
from papilio_panel.modules.jobs.models import Operation, OutboxMessage
from papilio_panel.modules.nodes.infra.schedules import initialize_nodes
from papilio_panel.modules.nodes.models import DeploymentIdentity

pytestmark = pytest.mark.django_db(transaction=True)


def test_node_upgrade_preserves_foundation_data_and_operator_schedule() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    foundation = [target for target in current if target[0] != "nodes"] + [("nodes", None)]
    executor.migrate(foundation)
    try:
        owner = User.objects.create_superuser(
            username="prior-owner", password="isolated-prior-password-596!"
        )
        operation = Operation.objects.create(actor=owner, request_key=uuid4(), kind="io")
        OutboxMessage.objects.create(operation=operation)
        interval, _ = IntervalSchedule.objects.get_or_create(every=13, period="seconds")
        schedule = PeriodicTask.objects.get(task=TaskName.DISPATCH.value)
        schedule.enabled = False
        schedule.interval = interval
        schedule.save()
    finally:
        MigrationExecutor(connection).migrate(current)
    initialize_nodes(sender=object())
    assert User.objects.get(pk=owner.pk).username == "prior-owner"
    assert Operation.objects.get(pk=operation.pk).status == "queued"
    assert OutboxMessage.objects.get(operation=operation).dispatched_at is None
    schedule.refresh_from_db()
    assert not schedule.enabled and schedule.interval is not None
    assert schedule.interval.every == 13
    assert DeploymentIdentity.objects.count() == 1
