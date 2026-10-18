import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.billing, pytest.mark.unit]


def test_outbox_migration_downgrade_drops_created_table(monkeypatch):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0065_receipt_ocr_outbox.py"
    )
    spec = importlib.util.spec_from_file_location(
        "receipt_outbox_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations = []

    class Operations:
        def drop_index(self, name: str, *, table_name: str) -> None:
            operations.append(("drop_index", name, table_name))

        def drop_table(self, name: str) -> None:
            operations.append(("drop_table", name))

    monkeypatch.setattr(migration, "op", Operations())

    migration.downgrade()

    assert operations[-1] == ("drop_table", "tbl_receipt_ocr_outboxes")
