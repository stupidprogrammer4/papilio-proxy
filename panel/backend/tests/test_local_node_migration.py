"""Upgrade nonempty existing metadata without creating or replacing a local binding."""

from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from test_nodes import node_input, owner_client

from papilio_panel.modules.cores.models import Core
from papilio_panel.modules.local_nodes.infra.schedules import initialize_local_nodes
from papilio_panel.modules.local_nodes.models import LocalNodeInstallation
from papilio_panel.modules.nodes.models import Node, NodeOperation, NodeOutbox

pytestmark = pytest.mark.django_db(transaction=True)


def test_local_runtime_upgrade_preserves_existing_nodes_work_and_operator_schedules() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] != "local_nodes"] + [("local_nodes", None)]
    executor.migrate(before)
    try:
        client = owner_client("before-local-runtime")
        created = client.post("/api/v1/nodes", node_input("retained-remote-node"), format="json")
        assert created.status_code == 202
        node_id, operation_id = created.json()["node"]["id"], created.json()["operation"]["id"]
        core = client.post(
            "/api/v1/cores/xray",
            {
                "request_key": str(uuid4()),
                "node_id": node_id,
                "name": "Existing attached core",
            },
            format="json",
        )
        assert core.status_code == 201
        schedule = PeriodicTask.objects.get(task="papilio.nodes.dispatch_outbox")
        interval, _ = IntervalSchedule.objects.get_or_create(every=23, period="seconds")
        schedule.enabled, schedule.interval = False, interval
        schedule.save()
    finally:
        MigrationExecutor(connection).migrate(current)
    initialize_local_nodes(sender=object())
    connection.close()
    assert Node.objects.get(pk=node_id).name == "retained-remote-node"
    assert Core.objects.get(pk=core.json()["id"]).name == "Existing attached core"
    assert NodeOperation.objects.get(pk=operation_id).status == "queued"
    assert NodeOutbox.objects.get(operation_id=operation_id).dispatched_at is None
    assert LocalNodeInstallation.objects.count() == 0
    schedule.refresh_from_db()
    assert schedule.enabled is False and schedule.interval is not None
    assert schedule.interval.every == 23
