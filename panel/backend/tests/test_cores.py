"""Register existing Xray cores/inbounds through scoped native API persistence."""

from uuid import uuid4

import pytest
from test_nodes import node_input, owner_client

pytestmark = pytest.mark.django_db(transaction=True)


def test_register_xray_and_inbound_is_scoped_configurable_and_replay_safe() -> None:
    owner = owner_client("core-owner")
    assert "cores:write" in owner.get("/api/v1/admin/auth/me").json()["scopes"]
    node = owner.post("/api/v1/nodes", node_input(), format="json").json()["node"]
    values = {
        "request_key": str(uuid4()),
        "node_id": node["id"],
        "name": "Native Xray",
        "default_user_level": 7,
    }
    created = owner.post("/api/v1/cores/xray", values, format="json")
    assert created.status_code == 201
    core = created.json()
    assert core["node_id"] == node["id"]
    assert core["xray"]["default_user_level"] == 7
    assert owner.post("/api/v1/cores/xray", values, format="json").json() == core
    assert (
        owner.post("/api/v1/cores/xray", values | {"name": "different"}, format="json").status_code
        == 409
    )
    endpoint = f"/api/v1/cores/{core['id']}/xray/inbounds"
    definition = {
        "request_key": str(uuid4()),
        "tag": "vless-first",
        "public_host": "127.0.0.1",
        "port": 10888,
    }
    response = owner.post(endpoint, definition, format="json")
    assert response.status_code == 201
    inbound = response.json()
    assert inbound["core_id"] == core["id"]
    assert inbound["port"] == 10888
    assert owner.post(endpoint, definition, format="json").json() == inbound
    assert owner.post(endpoint, definition | {"port": 10889}, format="json").status_code == 409
    assert owner.get(endpoint, {"q": "first"}).json()["items"][0]["id"] == inbound["id"]
    assert owner.get("/api/v1/cores", {"q": "Native", "page_size": 1}).json()["count"] == 1
    foreign = owner_client("other-core-owner")
    assert foreign.get(f"/api/v1/cores/{core['id']}").status_code == 404
    assert foreign.get(endpoint).status_code == 404
    assert (
        foreign.post(
            endpoint, definition | {"request_key": str(uuid4())}, format="json"
        ).status_code
        == 404
    )
    assert (
        foreign.post(
            "/api/v1/cores/xray", values | {"request_key": str(uuid4())}, format="json"
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"port": 0},
        {"port": 65536},
        {"tag": ""},
        {"public_host": "a.example/escape"},
        {"public_host": "user@host.example"},
    ],
)
def test_invalid_inbound_settings_are_not_persisted(changes: dict[str, object]) -> None:
    owner = owner_client("core-validation")
    node = owner.post("/api/v1/nodes", node_input(), format="json").json()["node"]
    core = owner.post(
        "/api/v1/cores/xray",
        {
            "request_key": str(uuid4()),
            "node_id": node["id"],
            "name": "Xray",
        },
        format="json",
    )
    assert core.status_code == 201
    endpoint = f"/api/v1/cores/{core.json()['id']}/xray/inbounds"
    result = owner.post(
        endpoint,
        {"request_key": str(uuid4()), "tag": "vless", "public_host": "example.com", "port": 443}
        | changes,
        format="json",
    )
    assert result.status_code == 400
    assert owner.get(endpoint).json()["count"] == 0


def test_inbound_parent_membership_duplicate_tags_and_complete_pagination() -> None:
    owner = owner_client("core-parent-owner")
    endpoints = []
    for name in ("first", "second"):
        node = owner.post("/api/v1/nodes", node_input(name), format="json").json()["node"]
        core = owner.post(
            "/api/v1/cores/xray",
            {
                "request_key": str(uuid4()),
                "node_id": node["id"],
                "name": name,
                "default_user_level": 4294967295,
            },
            format="json",
        )
        assert core.status_code == 201
        assert core.json()["xray"]["default_user_level"] == 4294967295
        endpoints.append(f"/api/v1/cores/{core.json()['id']}/xray/inbounds")
    first, second = endpoints
    definition = {"request_key": str(uuid4()), "tag": "east-a", "public_host": "::1", "port": 65535}
    created = owner.post(first, definition, format="json")
    assert created.status_code == 201
    assert owner.get(f"{second}/{created.json()['id']}").status_code == 404
    duplicate = owner.post(first, definition | {"request_key": str(uuid4())}, format="json")
    assert duplicate.status_code == 409
    assert owner.get(first).json()["count"] == 1
    assert (
        owner.post(
            first, definition | {"request_key": str(uuid4()), "tag": "east-b"}, format="json"
        ).status_code
        == 201
    )
    a = owner.get(first, {"q": "east", "page_size": 1}).json()
    b = owner.get(first, {"q": "east", "page_size": 1, "page": 2}).json()
    assert a["count"] == b["count"] == 2
    assert a["items"][0]["id"] != b["items"][0]["id"]
    assert owner.get(first, {"page": 0}).status_code == 400
    assert owner.get(first, {"page_size": 201}).status_code == 400
    assert owner.get(first, {"page": 9}).status_code == 404


def test_concurrent_registration_commits_one_common_and_specialized_core() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from django.contrib.auth.models import User
    from django.db import close_old_connections

    from papilio_panel.modules.cores.domain import XrayRegistration
    from papilio_panel.modules.cores.models import Core, XrayCore
    from papilio_panel.modules.cores.providers import cores
    from papilio_panel.modules.nodes.domain import NodeCreate, NodeDefinition
    from papilio_panel.modules.nodes.providers import nodes

    actor = User.objects.create_superuser(username="core-concurrent")
    node = nodes.create(
        NodeCreate(actor.pk, uuid4(), NodeDefinition("node", "https://node.example.com"))
    ).node
    values = XrayRegistration(actor.pk, uuid4(), node.id, "Xray")

    def register() -> bool:
        close_old_connections()
        try:
            return cores.register_xray(values).created
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = tuple(workers.map(lambda _: register(), range(2)))
    assert sorted(results) == [False, True]
    assert Core.objects.count() == XrayCore.objects.count() == 1
