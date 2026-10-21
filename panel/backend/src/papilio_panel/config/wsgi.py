"""Synchronous request workers keep blocking native work off any event loop."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "papilio_panel.config.settings")
application = get_wsgi_application()
