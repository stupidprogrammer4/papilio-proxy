"""Pure one-use administrative chat pairing policy over a bounded update batch."""

import hashlib
import hmac
import json
import re
from dataclasses import replace
from datetime import datetime

from ..domain import BotRead, IncomingUpdate, PairingState


def paired_chat(
    bot: BotRead, state: PairingState, updates: tuple[IncomingUpdate, ...], now: datetime
) -> int | None:
    if not state.digest or state.expires_at is None or state.expires_at <= now:
        return None
    for update in sorted(updates, key=lambda item: item.update_id):
        message = update.message
        if (
            message is None
            or message.chat_type != "private"
            or message.chat_id != message.sender_id
        ):
            continue
        parts = message.text.split()
        commands = {"/start", f"/start@{bot.username}"}
        if len(parts) != 2 or parts[0] not in commands:
            continue
        digest = hashlib.sha256(parts[1].encode()).hexdigest()
        if hmac.compare_digest(digest, state.digest):
            return message.chat_id
    return None


def retained_update(update: IncomingUpdate, state: PairingState) -> IncomingUpdate:
    content = json.dumps(update.payload)
    candidates = set(re.findall(r"pair_[A-Za-z0-9_-]{32}", content))
    sensitive = {
        parameter
        for parameter in candidates
        if state.digest
        and hmac.compare_digest(hashlib.sha256(parameter.encode()).hexdigest(), state.digest)
    }
    if update.message is not None:
        parts = update.message.text.split()
        if (
            len(parts) == 2
            and (parts[0] == "/start" or parts[0].startswith("/start@"))
            and parts[1] in candidates
        ):
            sensitive.add(parts[1])
    for parameter in sensitive:
        content = content.replace(parameter, "[pairing redacted]")
    return replace(update, payload=json.loads(content))


def retained_updates(
    updates: tuple[IncomingUpdate, ...], state: PairingState
) -> tuple[IncomingUpdate, ...]:
    """Retain ordinary text; remove active grants and pairing command capabilities."""
    return tuple(retained_update(update, state) for update in updates)
