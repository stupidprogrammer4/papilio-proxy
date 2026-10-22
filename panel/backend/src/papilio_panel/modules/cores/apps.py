"""Native persistence discovery for registered cores."""

from django.apps import AppConfig


class CoresConfig(AppConfig):
    name = "papilio_panel.modules.cores"
    label = "cores"
