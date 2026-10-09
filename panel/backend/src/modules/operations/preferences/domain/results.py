from pydantic import BaseModel

from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentIdentifierCapabilities,
)
from src.modules.operations.notifications.domain.dtos import NotificationKind
from src.modules.operations.preferences.domain.dtos import BusinessPreferences
from src.modules.sales.checkout.domain.contracts import TransientConflictAction


class PreferencesCapabilities(BaseModel):
    payment_identifiers: PaymentIdentifierCapabilities
    supported_notification_kinds: list[NotificationKind]
    checkout_transient_conflict_modes: list[TransientConflictAction]


class PreferencesSnapshot(BaseModel):
    capabilities: PreferencesCapabilities
    revision: int
    values: BusinessPreferences
