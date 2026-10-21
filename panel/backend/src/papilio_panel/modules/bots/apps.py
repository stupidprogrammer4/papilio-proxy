"""Native Django bot application discovery; no migration-time setting resets."""

from django.apps import AppConfig


class BotsConfig(AppConfig):
    name = "papilio_panel.modules.bots"
    label = "bots"
