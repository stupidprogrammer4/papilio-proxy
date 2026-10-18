import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.billing, pytest.mark.unit]


def test_receipt_annotation_migration_adds_revisioned_audit_table(monkeypatch):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0068_receipt_annotations.py"
    )
    spec = importlib.util.spec_from_file_location(
        "receipt_annotations_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations = []

    class Operations:
        def add_column(self, table_name, column):
            operations.append(("add_column", table_name, column.name))

        def create_table(self, name, *columns, **kwargs):
            operations.append(("create_table", name, columns, kwargs))

        def create_index(self, name, table_name, columns, **kwargs):
            operations.append(("create_index", name, table_name, columns))

    monkeypatch.setattr(migration, "op", Operations())

    migration.upgrade()

    assert (
        "add_column",
        "tbl_payment_receipts",
        "annotation_revision",
    ) in operations
    table = next(
        item
        for item in operations
        if item[:2] == ("create_table", "tbl_payment_receipt_annotations")
    )
    columns = {column.name: column for column in table[2]}
    expected = {
        "receipt_id",
        "revision",
        "staff_id",
        "encrypted_fields",
        "encrypted_reason",
    }
    assert expected <= columns.keys()
    assert any(item[0] == "create_index" for item in operations)
