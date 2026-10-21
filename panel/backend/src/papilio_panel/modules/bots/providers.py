"""Bind operator bot capabilities to native database and Telegram adapters."""

from papilio_panel.modules.identity.providers import admin_access

from .app.management import BotManagement
from .app.polling import BotPolling
from .infra.pairing import NativePairingIssuer
from .infra.storage import DjangoBotStorage
from .infra.telegram import NativeTelegramGateway
from .interfaces import BotCapability, BotPollingCapability

storage = DjangoBotStorage()
bots: BotCapability = BotManagement(storage, admin_access, NativePairingIssuer())
polling: BotPollingCapability = BotPolling(storage, admin_access, NativeTelegramGateway())
