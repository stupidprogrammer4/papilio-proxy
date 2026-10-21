"""Managed native Beat settings remain editable, validated and conflict-aware."""

import pytest
from django.contrib.auth.models import User
from test_job_contract import logged_in_client

pytestmark = pytest.mark.django_db(transaction=True)


def test_owner_can_edit_schedule_without_migrations_resetting_it() -> None:
    from papilio_panel.modules.jobs.infra.schedules import initialize_schedules

    client = logged_in_client("owner")
    rows = client.get("/api/v1/system/schedules").json()
    row = next(row for row in rows if row["key"] == "outbox")
    update = {"enabled": True, "interval_seconds": 4, "expected_changed_at": row["changed_at"]}
    response = client.put("/api/v1/system/schedules/outbox", update, format="json")
    assert response.status_code == 200
    assert response.json()["interval_seconds"] == 4
    assert client.put("/api/v1/system/schedules/outbox", update, format="json").status_code == 409
    initialize_schedules(sender=object())
    row = next(
        row for row in client.get("/api/v1/system/schedules").json() if row["key"] == "outbox"
    )
    assert row["interval_seconds"] == 4


def test_schedule_updates_require_owner_and_validate_native_bounds() -> None:
    client = logged_in_client("owner")
    row = client.get("/api/v1/system/schedules").json()[0]
    values = {"enabled": False, "interval_seconds": 0, "expected_changed_at": row["changed_at"]}
    assert (
        client.put(f"/api/v1/system/schedules/{row['key']}", values, format="json").status_code
        == 400
    )
    values["interval_seconds"] = 1
    User.objects.filter(username="owner").update(is_superuser=False)
    assert client.get("/api/v1/system/schedules").status_code == 401
    assert (
        client.put(f"/api/v1/system/schedules/{row['key']}", values, format="json").status_code
        == 401
    )


def test_unknown_schedule_cannot_register_arbitrary_tasks() -> None:
    client = logged_in_client("owner")
    assert client.put("/api/v1/system/schedules/unknown", {}, format="json").status_code == 404


def test_native_beat_run_does_not_invalidate_unchanged_configuration() -> None:
    from django.conf import settings
    from django_celery_beat.models import PeriodicTask
    from kombu.utils.imports import symbol_by_name

    from papilio_panel.config.celery import app

    client = logged_in_client("owner")
    row = next(
        row for row in client.get("/api/v1/system/schedules").json() if row["key"] == "outbox"
    )
    model = PeriodicTask.objects.get(name=f"{settings.PAPILIO_NAMESPACE}.outbox")
    entry_class = symbol_by_name(settings.CELERY_BEAT_SCHEDULER).Entry
    entry = next(entry_class(model, app=app))
    entry.save()
    response = client.put(
        "/api/v1/system/schedules/outbox",
        {"enabled": True, "interval_seconds": 4, "expected_changed_at": row["changed_at"]},
        format="json",
    )
    assert response.status_code == 200


def test_native_run_metadata_save_cannot_overwrite_concurrent_settings() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from typing import Any

    from django.conf import settings
    from django.db import close_old_connections, connection
    from django_celery_beat.models import PeriodicTask
    from kombu.utils.imports import symbol_by_name

    from papilio_panel.config.celery import app
    from papilio_panel.modules.jobs.domain import ScheduleKind, ScheduleUpdate
    from papilio_panel.modules.jobs.providers import managed_schedules

    client = logged_in_client("owner")
    owner = User.objects.get(username="owner")
    original = next(
        row for row in managed_schedules.read_all(owner.pk) if row.key == ScheduleKind.OUTBOX
    )
    model = PeriodicTask.objects.get(name=f"{settings.PAPILIO_NAMESPACE}.outbox")
    entry_class = symbol_by_name(settings.CELERY_BEAT_SCHEDULER).Entry
    entry = next(entry_class(model, app=app))

    def change_setting() -> None:
        close_old_connections()
        try:
            managed_schedules.update(
                owner.pk,
                ScheduleUpdate(
                    key=ScheduleKind.OUTBOX,
                    enabled=True,
                    interval_seconds=7,
                    expected_changed_at=original.changed_at,
                ),
            )
        finally:
            close_old_connections()

    def concurrent_edit(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
        # Inject the real, independent committed edit immediately before Beat's UPDATE.
        if sql.startswith("UPDATE") and PeriodicTask._meta.db_table in sql:
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(change_setting).result(timeout=10)
        result = execute(sql, params, many, context)
        return result

    with connection.execute_wrapper(concurrent_edit):
        entry.save()
    rows = client.get("/api/v1/system/schedules").json()
    updated = next(row for row in rows if row["key"] == "outbox")
    assert updated["interval_seconds"] == 7
