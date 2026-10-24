"""Real PostgreSQL leases, generations and set-based synchronization publication."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from django.db import close_old_connections, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from test_service_synchronization import synchronization_context

from papilio_panel.config.celery import app
from papilio_panel.modules.services.infra.synchronization import DjangoServiceSynchronizationStorage
from papilio_panel.modules.services.models import ServiceAccount
from papilio_panel.modules.services.providers import synchronizations
from papilio_panel.modules.services.synchronization_contracts import (
    SynchronizationDelivery,
    SynchronizationTaskName,
    SynchronizationUpdate,
)
from papilio_panel.shared.errors import Conflict

pytestmark = pytest.mark.django_db(transaction=True)


def due_service() -> tuple[UUID, str]:
    _, url, identifier = synchronization_context()
    ServiceAccount.objects.filter(pk=identifier).update(
        status="succeeded", sync_due_at=timezone.now() - timedelta(seconds=1)
    )
    return UUID(identifier), url


@pytest.mark.parametrize("generation", [1.5, True])
def test_noninteger_background_generations_are_rejected_before_reservation(
    generation: object,
) -> None:
    identifier, _ = due_service()
    result = app.tasks[SynchronizationTaskName.SYNCHRONIZE.value].apply(
        kwargs={"service_id": str(identifier), "generation": generation}
    )
    assert result.failed()
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.sync_attempts == 0 and row.sync_generation == 1 and row.sync_status == "queued"


def test_concurrent_native_claims_have_one_current_lease() -> None:
    identifier, _ = due_service()
    barrier = Barrier(2)

    def claim() -> object:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return DjangoServiceSynchronizationStorage().claim(identifier, 1)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(claim) for _ in range(2))
        claims = tuple(future.result(timeout=10) for future in futures)
    assert sum(claim is not None for claim in claims) == 1
    connection.close()
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.sync_attempts == 1 and row.attempts == 0 and row.sync_status == "running"


def test_late_publisher_cannot_stamp_the_next_generation() -> None:
    identifier, _ = due_service()
    storage = DjangoServiceSynchronizationStorage()
    deliveries = storage.pending()
    assert tuple(item.service_id for item in deliveries) == (identifier,)
    claim = storage.claim(identifier, 1)
    assert claim is not None
    storage.finish(claim, None)
    storage.dispatched(deliveries)
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.sync_generation == 2 and row.sync_dispatched_at is None


def test_dispatch_marking_is_one_native_write_for_mixed_known_and_missing_members() -> None:
    identifier, _ = due_service()
    storage = DjangoServiceSynchronizationStorage()
    deliveries = (
        SynchronizationDelivery(identifier, 1, 10),
        SynchronizationDelivery(uuid4(), 1, 10),
    )
    with CaptureQueriesContext(connection) as queries:
        storage.dispatched(deliveries)
    assert len(queries) == 1
    assert ServiceAccount.objects.get(pk=identifier).sync_dispatched_at is not None
    with CaptureQueriesContext(connection) as empty:
        storage.dispatched(())
    assert len(empty) == 0


def test_policy_change_invalidates_old_leases_and_publication() -> None:
    client, url, identifier = synchronization_context()
    ServiceAccount.objects.filter(pk=identifier).update(
        status="succeeded", sync_due_at=timezone.now() - timedelta(seconds=1)
    )
    storage = DjangoServiceSynchronizationStorage()
    claim = storage.claim(UUID(identifier), 1)
    assert claim is not None and storage.active(claim)
    changed = client.put(
        url,
        {
            "enabled": False,
            "interval_seconds": 5,
            "expected_revision": "1",
        },
        format="json",
    )
    assert changed.status_code == 200
    assert not storage.active(claim)
    storage.finish(claim, None)
    assert not storage.pending()
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.sync_status == "queued" and row.sync_last_completed_at is None
    assert row.sync_generation == 2 and row.sync_attempts == 1 and row.status == "succeeded"


def test_expired_claim_is_recovered_without_acknowledging_a_late_worker() -> None:
    identifier, _ = due_service()
    storage = DjangoServiceSynchronizationStorage()
    old = storage.claim(identifier, 1)
    assert old is not None
    ServiceAccount.objects.filter(pk=identifier).update(
        sync_lease_until=timezone.now() - timedelta(seconds=1)
    )
    current = storage.claim(identifier, 1)
    assert current is not None and current.token != old.token
    storage.finish(old, None)
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.sync_status == "running" and row.sync_lease_token == current.token
    storage.finish(current, "core_unavailable")
    row.refresh_from_db()
    assert row.sync_status == "failed" and row.sync_error_code == "core_unavailable"
    assert row.sync_generation == 2 and row.sync_attempts == 2
    assert row.sync_due_at > timezone.now() and row.status == "succeeded" and row.attempts == 0


def test_concurrent_settings_updates_have_one_revision_winner() -> None:
    identifier, _ = due_service()
    actor_id = ServiceAccount.objects.get(pk=identifier).owner_id
    barrier = Barrier(2)

    def configure(interval: int) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            synchronizations.update(SynchronizationUpdate(actor_id, identifier, False, interval, 1))
            return "saved"
        except Conflict:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(configure, interval) for interval in (7, 11))
        outcomes = tuple(future.result(timeout=10) for future in futures)
    assert sorted(outcomes) == ["conflict", "saved"]
    connection.close()
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.sync_revision == 2 and row.sync_generation == 2
    assert row.sync_interval_seconds in {7, 11} and row.sync_enabled is False


def test_a_policy_edit_between_reservation_and_read_cannot_fabricate_a_new_claim() -> None:
    identifier, _ = due_service()
    actor_id = ServiceAccount.objects.get(pk=identifier).owner_id
    assert not connection.in_atomic_block

    def pause() -> None:
        close_old_connections()
        try:
            synchronizations.update(SynchronizationUpdate(actor_id, identifier, False, 7, 1))
        finally:
            close_old_connections()

    from typing import Any

    def edit_after_reservation(
        execute: Any, sql: str, params: Any, many: bool, context: Any
    ) -> Any:
        result = execute(sql, params, many, context)
        if sql.startswith("UPDATE") and ServiceAccount._meta.db_table in sql:
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(pause).result(timeout=10)
        return result

    with connection.execute_wrapper(edit_after_reservation):
        claim = DjangoServiceSynchronizationStorage().claim(identifier, 1)
    assert claim is None
    row = ServiceAccount.objects.get(pk=identifier)
    assert row.sync_generation == 2 and row.sync_enabled is False and row.sync_lease_token is None
