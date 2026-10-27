"""Node onboarding contracts through native HTTP and real PostgreSQL."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db(transaction=True)


def owner_client(name: str = "node-owner", *, superuser: bool = True) -> APIClient:
    user = User.objects.create_user(
        username=name,
        password="isolated-node-owner-password-944!",
        is_staff=True,
        is_superuser=superuser,
    )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/admin/auth/csrf").json()["csrf_token"]
    client.credentials(HTTP_X_CSRF_TOKEN=csrf)
    session = client.post(
        "/api/v1/admin/auth/login",
        {
            "username": user.username,
            "password": "isolated-node-owner-password-944!",
        },
        format="json",
    )
    assert session.status_code == 200
    client.credentials(HTTP_X_CSRF_TOKEN=session.json()["csrf_token"])
    return client


def node_input(name: str = "first-node") -> dict[str, object]:
    return {
        "request_key": str(uuid4()),
        "name": name,
        "endpoint_url": "https://node.example.invalid:9443",
        "runtime": {"listen_address": "0.0.0.0:9443", "request_timeout_seconds": 17},
    }


def test_node_create_is_durable_asynchronous_and_idempotent() -> None:
    client = owner_client()
    values = node_input()
    first = client.post("/api/v1/nodes", values, format="json")
    assert first.status_code == 202
    result = first.json()
    assert result["node"]["name"] == "first-node"
    assert result["node"]["runtime"]["request_timeout_seconds"] == 17
    assert result["node"]["credentials_ready"] is False
    assert result["node"]["last_reachable"] is None
    assert result["operation"]["status"] == "queued"
    assert result["operation"]["kind"] == "issue_credentials"
    assert client.post("/api/v1/nodes", values, format="json").json() == result
    altered = values | {"name": "different"}
    assert client.post("/api/v1/nodes", altered, format="json").status_code == 409
    listed = client.get("/api/v1/nodes").json()
    assert listed["count"] == 1
    assert listed["items"][0]["id"] == result["node"]["id"]
    assert client.post(f"/api/v1/nodes/{result['node']['id']}/bootstrap").status_code == 409


def test_scope_checks_apply_to_node_operations_and_private_bootstrap() -> None:
    first = owner_client("first")
    second = owner_client("second")
    made = first.post("/api/v1/nodes", node_input(), format="json")
    assert made.status_code == 202
    node = made.json()["node"]
    operation = made.json()["operation"]
    root = f"/api/v1/nodes/{node['id']}"
    assert second.get(root).status_code == 404
    assert second.post(root + "/bootstrap").status_code == 404
    assert second.get(root + f"/operations/{operation['id']}").status_code == 404
    assert (
        second.post(
            root + "/operations",
            {
                "kind": "check_connection",
                "request_key": str(uuid4()),
            },
            format="json",
        ).status_code
        == 404
    )
    assert second.get("/api/v1/nodes").json()["count"] == 0
    staff = owner_client("staff", superuser=False)
    assert staff.post("/api/v1/nodes", node_input(), format="json").status_code in {401, 403}
    assert first.get(root).json()["credentials_ready"] is False


@pytest.mark.parametrize(
    "override",
    [
        {"endpoint_url": "http://node.example.invalid:9443"},
        {"endpoint_url": "https://user:password@node.example.invalid:9443"},
        {"endpoint_url": "https://node.example.invalid:9443/private"},
        {"runtime": {"request_timeout_seconds": 0}},
        {"runtime": {"request_timeout_seconds": 2147483648}},
        {"runtime": {"xray_api_address": "192.0.2.1:10085"}},
        {"certificate_policy": {"validity_seconds": 100, "authority_validity_seconds": 50}},
    ],
)
def test_invalid_node_inputs_leave_no_record(override: dict[str, object]) -> None:
    client = owner_client()
    response = client.post("/api/v1/nodes", node_input() | override, format="json")
    assert response.status_code == 400
    assert client.get("/api/v1/nodes").json()["count"] == 0


def test_nested_operation_parent_cannot_be_changed() -> None:
    client = owner_client()
    first = client.post("/api/v1/nodes", node_input("first"), format="json")
    second = client.post("/api/v1/nodes", node_input("second"), format="json")
    assert first.status_code == second.status_code == 202
    target = second.json()["node"]["id"]
    foreign = first.json()["operation"]["id"]
    assert client.get(f"/api/v1/nodes/{target}/operations/{foreign}").status_code == 404


def test_search_and_pagination_cover_the_authorized_collection() -> None:
    client = owner_client()
    for name in ("east-one", "west-one", "east-two"):
        assert client.post("/api/v1/nodes", node_input(name), format="json").status_code == 202
    first = client.get("/api/v1/nodes", {"q": "east", "page_size": 1}).json()
    second = client.get("/api/v1/nodes", {"q": "east", "page_size": 1, "page": 2}).json()
    assert first["count"] == second["count"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert client.get("/api/v1/nodes", {"page": 0}).status_code == 400


def test_create_key_cannot_reuse_an_existing_node_operation_key() -> None:
    client = owner_client()
    first = client.post("/api/v1/nodes", node_input(), format="json").json()
    key = str(uuid4())
    response = client.post(
        f"/api/v1/nodes/{first['node']['id']}/operations",
        {"request_key": key, "kind": "check_connection"},
        format="json",
    )
    assert response.status_code == 202
    result = client.post("/api/v1/nodes", node_input("other") | {"request_key": key}, format="json")
    assert result.status_code == 409
    assert client.get("/api/v1/nodes").json()["count"] == 1


def test_onboarding_defaults_are_owner_scoped_and_match_persisted_choices() -> None:
    owner = owner_client()
    response = owner.get("/api/v1/nodes/defaults")
    assert response.status_code == 200
    defaults = response.json()
    assert defaults["runtime"]["request_timeout_seconds"] == 15
    assert defaults["certificate_policy"]["validity_seconds"] == 2592000
    created = owner.post("/api/v1/nodes", node_input() | defaults, format="json")
    assert created.status_code == 202
    assert created.json()["node"]["runtime"] == defaults["runtime"]
    staff = owner_client("staff", superuser=False)
    assert staff.get("/api/v1/nodes/defaults").status_code in {401, 403}


def test_concurrent_node_creation_has_one_node_operation_and_outbox() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections

    from papilio_panel.modules.nodes.domain import NodeCreate, NodeDefinition
    from papilio_panel.modules.nodes.models import Node, NodeOperation, NodeOutbox
    from papilio_panel.modules.nodes.providers import nodes

    user = User.objects.create_superuser(
        username="concurrent-owner", password="isolated-password-578!"
    )
    values = NodeCreate(
        actor_id=user.pk,
        request_key=uuid4(),
        definition=NodeDefinition(
            name="concurrent", endpoint_url="https://node.example.invalid:9443"
        ),
    )

    def create() -> object:
        close_old_connections()
        try:
            result = nodes.create(values)
            return result.operation.id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: create(), range(4)))
    assert len(set(results)) == 1
    assert Node.objects.count() == NodeOperation.objects.count() == NodeOutbox.objects.count() == 1


def test_wrong_task_kind_and_revoked_owner_cannot_issue_credentials() -> None:
    from papilio_panel.config.celery import app
    from papilio_panel.modules.nodes.domain import NodeTaskName
    from papilio_panel.modules.nodes.models import NodeCredentials

    client = owner_client()
    created = client.post("/api/v1/nodes", node_input(), format="json").json()
    node, operation = created["node"], created["operation"]
    operation_url = f"/api/v1/nodes/{node['id']}/operations/{operation['id']}"
    app.tasks[NodeTaskName.CHECK.value].apply(kwargs={"operation_id": operation["id"]}, throw=True)
    unchanged = client.get(operation_url).json()
    assert unchanged["status"] == "queued"
    assert unchanged["attempts"] == 0
    User.objects.filter(username="node-owner").update(is_superuser=False)
    app.tasks[NodeTaskName.ISSUE.value].apply(kwargs={"operation_id": operation["id"]}, throw=True)
    assert not NodeCredentials.objects.exists()
    User.objects.filter(username="node-owner").update(is_superuser=True)
    rejected = client.get(operation_url).json()
    assert rejected["status"] == "failed"
    assert rejected["error_code"] == "access_revoked"


def test_node_schedule_seed_preserves_disabled_operator_setting() -> None:
    from papilio_panel.modules.nodes.infra.schedules import initialize_nodes

    client = owner_client()
    rows = client.get("/api/v1/system/schedules").json()
    row = next(item for item in rows if item["key"] == "node-outbox")
    response = client.put(
        "/api/v1/system/schedules/node-outbox",
        {"enabled": False, "interval_seconds": 9, "expected_changed_at": row["changed_at"]},
        format="json",
    )
    assert response.status_code == 200
    initialize_nodes(sender=object())
    updated = next(
        item
        for item in client.get("/api/v1/system/schedules").json()
        if item["key"] == "node-outbox"
    )
    assert updated == response.json()


def test_owner_updates_node_configuration_with_revision_and_preserves_identity() -> None:
    client = owner_client()
    created = client.post("/api/v1/nodes", node_input(), format="json").json()
    node = created["node"]
    path = f"/api/v1/nodes/{node['id']}"
    update = {
        "expected_revision": node["configuration_revision"],
        "runtime": node["runtime"] | {"request_timeout_seconds": 23},
        "certificate_policy": node["certificate_policy"] | {"backdate_seconds": 90},
    }

    response = client.put(path, update, format="json")

    assert response.status_code == 200
    saved = response.json()
    assert saved["configuration_revision"] == node["configuration_revision"] + 1
    assert saved["runtime"]["request_timeout_seconds"] == 23
    assert saved["certificate_policy"]["backdate_seconds"] == 90
    assert saved["endpoint_url"] == node["endpoint_url"]
    assert saved["owner_id"] == node["owner_id"]
    assert saved["credentials_ready"] is False
    assert client.get(path).json() == saved


def test_node_configuration_update_conflict_invalid_values_and_owner_scope() -> None:
    first = owner_client("first")
    second = owner_client("second")
    created = first.post("/api/v1/nodes", node_input(), format="json").json()
    node = created["node"]
    path = f"/api/v1/nodes/{node['id']}"
    update = {
        "expected_revision": node["configuration_revision"],
        "runtime": node["runtime"] | {"request_timeout_seconds": 23},
        "certificate_policy": node["certificate_policy"],
    }
    assert first.put(path, update, format="json").status_code == 200

    stale = first.put(path, update, format="json")
    invalid = first.put(
        path,
        update
        | {
            "expected_revision": 2,
            "runtime": update["runtime"] | {"request_timeout_seconds": 0},
        },
        format="json",
    )
    incomplete = first.put(
        path,
        {"expected_revision": 2, "runtime": update["runtime"]},
        format="json",
    )

    assert stale.status_code == 409
    assert invalid.status_code == 400
    assert incomplete.status_code == 400
    current = first.get(path).json()
    assert current["configuration_revision"] == 2
    assert current["runtime"]["request_timeout_seconds"] == 23
    assert second.put(path, update, format="json").status_code == 404


def test_concurrent_node_configuration_updates_have_one_revision_winner() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from django.contrib.auth.models import User
    from django.db import close_old_connections

    primary = owner_client("concurrent-settings")
    owner = User.objects.get(username="concurrent-settings")
    created = primary.post("/api/v1/nodes", node_input(), format="json").json()
    node = created["node"]
    path = f"/api/v1/nodes/{node['id']}"

    def update(timeout: int) -> int:
        close_old_connections()
        try:
            client = APIClient(enforce_csrf_checks=True)
            csrf = client.get("/api/v1/admin/auth/csrf").json()["csrf_token"]
            client.credentials(HTTP_X_CSRF_TOKEN=csrf)
            session = client.post(
                "/api/v1/admin/auth/login",
                {"username": owner.username, "password": "isolated-node-owner-password-944!"},
                format="json",
            )
            client.credentials(HTTP_X_CSRF_TOKEN=session.json()["csrf_token"])
            payload = {
                "expected_revision": node["configuration_revision"],
                "runtime": node["runtime"] | {"request_timeout_seconds": timeout},
                "certificate_policy": node["certificate_policy"],
            }
            response = client.put(path, payload, format="json")
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        statuses = tuple(workers.map(update, (31, 37)))

    assert sorted(statuses) == [200, 409]
    current = primary.get(path).json()
    assert current["configuration_revision"] == 2
    assert current["runtime"]["request_timeout_seconds"] in {31, 37}
