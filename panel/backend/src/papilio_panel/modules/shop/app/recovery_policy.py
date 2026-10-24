"""Pure recovery availability, revision/key checks and operator-note validation."""

from dataclasses import replace
from datetime import datetime

from rest_framework import serializers

from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import MessageRead, MessageState, RecoveryAction, WorkState
from ..recovery_contracts import InspectionWindow, RecoveryAudit, RecoveryDefinition, WorkInspection
from .validation import revision


def work_actions(record: WorkInspection, now: datetime) -> tuple[RecoveryAction, ...]:
    if record.status == WorkState.FAILED or (
        record.status == WorkState.RUNNING
        and record.lease_until is not None
        and record.lease_until <= now
    ):
        return (RecoveryAction.RETRY, RecoveryAction.CANCEL)
    if record.status == WorkState.CANCELLED:
        return (RecoveryAction.RETRY,)
    if record.status == WorkState.QUEUED:
        return (RecoveryAction.CANCEL,)
    return ()


def message_actions(record: MessageRead, now: datetime) -> tuple[RecoveryAction, ...]:
    if record.status in {MessageState.FAILED, MessageState.AMBIGUOUS} or (
        record.status == MessageState.SENDING
        and record.lease_until is not None
        and record.lease_until <= now
    ):
        return (RecoveryAction.RETRY, RecoveryAction.CANCEL)
    if record.status == MessageState.CANCELLED:
        return (RecoveryAction.RETRY,)
    if record.status in {MessageState.QUEUED, MessageState.RETRY}:
        return (RecoveryAction.CANCEL,)
    return ()


def definition(values: RecoveryDefinition) -> RecoveryDefinition:
    revision(values.expected_revision)
    if not isinstance(values.action, RecoveryAction):
        raise InvalidInput("Choose retry or cancel.")
    note = serializers.CharField(max_length=500, allow_blank=True).run_validation(values.note)
    return replace(values, note=note)


def window(values: InspectionWindow, max_page_size: int) -> None:
    if (
        type(values.page) is not int
        or not 1 <= values.page <= 2147483647
        or type(values.page_size) is not int
        or not 1 <= values.page_size <= max_page_size
        or not isinstance(values.query, str)
        or len(values.query) > 200
    ):
        raise InvalidInput("Choose a supported search and pagination window.")


def require_action(
    values: RecoveryDefinition, current_revision: int, actions: tuple[RecoveryAction, ...]
) -> None:
    if values.expected_revision != current_revision:
        raise Conflict("The record changed. Reload its current state before recovery.")
    if values.action not in actions:
        raise Conflict("This recovery action is not available in the current state.")


def require_same_definition(audit: RecoveryAudit, values: RecoveryDefinition) -> None:
    if (
        audit.request_key != values.request_key
        or audit.expected_revision != values.expected_revision
        or audit.action != values.action
        or audit.note != values.note
    ):
        raise Conflict("This recovery request key already belongs to different input.")
