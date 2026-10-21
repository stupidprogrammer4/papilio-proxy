"""Execution resource ownership and HTTP paths."""

from django.urls import path

from .health import SystemStatusView
from .operations import CancelOperationView, OperationView, ProbeView
from .schedules import SchedulesView, ScheduleView

urlpatterns = [
    path("system/schedules", SchedulesView.as_view()),
    path("system/schedules/<str:schedule_key>", ScheduleView.as_view()),
    path("system/status", SystemStatusView.as_view()),
    path("system/probes", ProbeView.as_view()),
    path("system/operations/<uuid:operation_id>", OperationView.as_view()),
    path("system/operations/<uuid:operation_id>/cancel", CancelOperationView.as_view()),
]
