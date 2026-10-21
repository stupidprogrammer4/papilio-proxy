"""Native Celery application and Django task discovery."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "papilio_panel.config.settings")
app = Celery("papilio")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
