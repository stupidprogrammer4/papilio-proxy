#!/usr/bin/env python3
"""Run Papilio's native Django management commands."""

import os
import sys

from django.core.management import execute_from_command_line

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "papilio_panel.config.settings")
execute_from_command_line(sys.argv)
