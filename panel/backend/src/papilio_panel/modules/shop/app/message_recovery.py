"""Retry only stored replies or cancel future delivery, without business replay."""

from dataclasses import replace

from django.db import transaction

from papilio_panel.shared.errors import Conflict

from ..domain import MessageState, RecoveryAction
from ..interfaces import ShopMessageInspectionCapability, ShopMessageStorage
from ..recovery_contracts import MessageRecoveryInput, MessageRecoveryResult, MessageRecoveryWrite
from .recovery_policy import definition, require_action, require_same_definition


class ShopMessageRecovery:
    def __init__(
        self, storage: ShopMessageStorage, inspection: ShopMessageInspectionCapability
    ) -> None:
        self.storage = storage
        self.inspection = inspection

    @transaction.atomic
    def recover(self, values: MessageRecoveryInput) -> MessageRecoveryResult:
        current = self.inspection.read(values.bot_id, values.message_id, values.actor_id)
        inputs = replace(values, definition=definition(values.definition))
        prior = self.storage.recovery(inputs.actor_id, inputs.definition.request_key)
        if prior is not None:
            require_same_definition(prior, inputs.definition)
            if prior.bot_id != inputs.bot_id or prior.message_id != inputs.message_id:
                raise Conflict("This recovery key belongs to a different outgoing message.")
            return MessageRecoveryResult(prior, current, False)
        require_action(inputs.definition, current.revision, current.actions)
        retrying = inputs.definition.action == RecoveryAction.RETRY
        saved = self.storage.recover(
            MessageRecoveryWrite(
                inputs,
                current,
                MessageState.QUEUED if retrying else MessageState.CANCELLED,
                0 if retrying else current.attempts,
                None if retrying else current.error_code,
            )
        )
        require_same_definition(saved.recovery, inputs.definition)
        if saved.recovery.bot_id != inputs.bot_id or saved.recovery.message_id != inputs.message_id:
            raise Conflict("This recovery key belongs to a different outgoing message.")
        result = self.inspection.read(inputs.bot_id, inputs.message_id, inputs.actor_id)
        return MessageRecoveryResult(saved.recovery, result, saved.created)
