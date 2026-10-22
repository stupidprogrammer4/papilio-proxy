"""New core tables preserve nonempty prior node/auth/outbox state."""

from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from test_nodes import node_input, owner_client

from papilio_panel.modules.nodes.models import Node, NodeOperation, NodeOutbox

pytestmark = pytest.mark.django_db(transaction=True)


def test_core_migration_preserves_existing_node_and_pending_work() -> None:
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    before = [target for target in current if target[0] != "cores"] + [("cores", None)]
    executor.migrate(before)
    try:
        owner = owner_client("before-cores")
        created = owner.post("/api/v1/nodes", node_input("retained-node"), format="json")
        assert created.status_code == 202
        node_id = created.json()["node"]["id"]
        operation_id = created.json()["operation"]["id"]
    finally:
        MigrationExecutor(connection).migrate(current)
    connection.close()
    assert Node.objects.get(pk=node_id).name == "retained-node"
    assert NodeOperation.objects.get(pk=operation_id).status == "queued"
    assert NodeOutbox.objects.get(operation_id=operation_id).dispatched_at is None
    response = owner.post(
        "/api/v1/cores/xray",
        {"request_key": str(uuid4()), "node_id": node_id, "name": "Retained native node"},
        format="json",
    )
    assert response.status_code == 201
