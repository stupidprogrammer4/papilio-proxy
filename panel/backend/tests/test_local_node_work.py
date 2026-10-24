"""Real PostgreSQL delivery fencing, replay, retry and operator pause semantics."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone
from test_local_node_setup import initialize_local_owner

from papilio_panel.modules.local_nodes.models import LocalNodeOperation
from papilio_panel.shared.errors import Missing

pytestmark = pytest.mark.django_db(transaction=True)


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_retry_supersedes_old_work_without_allowing_old_completion_or_replay() -> None:
    from papilio_panel.modules.local_nodes.infra.work import DjangoLocalWorkStorage

    client = initialize_local_owner()
    work = DjangoLocalWorkStorage()
    root = "/api/v1/system/local-node"
    old = UUID(client.get(root).json()["operation"]["id"])
    claim = work.claim(old)
    assert claim is not None and work.active(claim)
    key = str(uuid4())
    response = client.post(root + "/operations", {"request_key": key}, format="json")
    assert response.status_code == 202
    new = response.json()["id"]
    assert new != str(old) and not work.active(claim)
    work.finish(claim, None, retryable=False)
    connection.close()
    assert LocalNodeOperation.objects.get(pk=old).status == "cancelled"
    assert LocalNodeOperation.objects.get(pk=new).status == "queued"
    replay = client.post(root + "/operations", {"request_key": key}, format="json")
    assert replay.status_code == 202 and replay.json()["id"] == new
    assert LocalNodeOperation.objects.count() == 2
    assert client.get(root).json()["operation"]["id"] == new
    with pytest.raises(Missing):
        work.read(uuid4())


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_pause_defers_completion_and_expired_lease_is_fenced_with_bounded_retries() -> None:
    from papilio_panel.modules.local_nodes.infra.work import DjangoLocalWorkStorage

    client = initialize_local_owner()
    root, work = "/api/v1/system/local-node", DjangoLocalWorkStorage()
    identifier = UUID(client.get(root).json()["operation"]["id"])
    claim = work.claim(identifier)
    assert claim is not None and work.claim(identifier) is None
    response = client.put(
        root + "/delivery",
        {
            "enabled": False,
            "retry_interval_seconds": 3,
            "max_attempts": 3,
            "expected_revision": "1",
        },
        format="json",
    )
    assert response.status_code == 200 and not work.active(claim)
    work.finish(claim, None, retryable=False)
    assert work.claim(identifier) is None and work.pending() is None
    assert LocalNodeOperation.objects.get(pk=identifier).status == "queued"
    assert (
        client.put(
            root + "/delivery",
            {
                "enabled": True,
                "retry_interval_seconds": 3,
                "max_attempts": 3,
                "expected_revision": "2",
            },
            format="json",
        ).status_code
        == 200
    )
    recovered = work.claim(identifier)
    assert recovered is not None
    LocalNodeOperation.objects.filter(pk=identifier).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    replacement = work.claim(identifier)
    assert replacement is not None and replacement.token != recovered.token
    work.finish(recovered, None, retryable=False)
    assert work.active(replacement)
    work.finish(replacement, "node_unreachable", retryable=True)
    connection.close()
    row = LocalNodeOperation.objects.get(pk=identifier)
    assert row.status == "failed" and row.attempts == 3
    assert row.error_code == "node_unreachable" and row.completed_at is not None
    assert work.pending() is None


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_independent_concurrent_workers_claim_only_one_current_lease() -> None:
    from papilio_panel.modules.local_nodes.infra.work import DjangoLocalWorkStorage

    client = initialize_local_owner()
    identifier = UUID(client.get("/api/v1/system/local-node").json()["operation"]["id"])
    barrier = Barrier(2)

    def claim_work() -> bool:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return DjangoLocalWorkStorage().claim(identifier) is not None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(claim_work) for _ in range(2)]
        assert sorted(future.result(timeout=10) for future in futures) == [False, True]
    connection.close()
    assert LocalNodeOperation.objects.get(pk=identifier).attempts == 1


@override_settings(PAPILIO_LOCAL_NODE_AVAILABLE=True)
def test_expired_running_delivery_respects_redelivery_bookmarks_and_policy_resume() -> None:
    from papilio_panel.modules.local_nodes.infra.work import DjangoLocalWorkStorage

    client = initialize_local_owner()
    root, work = "/api/v1/system/local-node", DjangoLocalWorkStorage()
    identifier = UUID(client.get(root).json()["operation"]["id"])
    claim = work.claim(identifier)
    assert claim is not None
    LocalNodeOperation.objects.filter(pk=identifier).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    delivery = work.pending()
    assert delivery is not None and delivery.operation_id == identifier
    work.dispatched(delivery)
    connection.close()
    assert work.pending() is None
    assert (
        client.put(
            root + "/delivery",
            {
                "enabled": False,
                "retry_interval_seconds": 2,
                "max_attempts": 9,
                "expected_revision": "1",
            },
            format="json",
        ).status_code
        == 200
    )
    assert work.pending() is None
    assert (
        client.put(
            root + "/delivery",
            {
                "enabled": True,
                "retry_interval_seconds": 2,
                "max_attempts": 9,
                "expected_revision": "2",
            },
            format="json",
        ).status_code
        == 200
    )
    assert work.pending() is not None
    recovered = work.claim(identifier)
    assert recovered is not None and recovered.token != claim.token
    work.dispatched(delivery)
    assert LocalNodeOperation.objects.get(pk=identifier).dispatched_at is None
