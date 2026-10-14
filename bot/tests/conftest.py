"""Identify the Telegram adapter suite using native pytest markers."""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep capability selection independent from integration evidence."""
    for item in items:
        item.add_marker("bot")
