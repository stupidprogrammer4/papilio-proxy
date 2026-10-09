"""Keep configurable JSON documents within the encrypted payload boundary."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision: str = "0039_configuration_json_payloads"
down_revision: str | None = "0038_configuration_json_history"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None
PAYLOAD_COLUMNS = (
    ("tbl_configurations", "encrypted_settings"),
    ("tbl_configuration_json_revisions", "encrypted_settings"),
    ("tbl_provision_tasks", "encrypted_payload"),
)
# Native MySQL TEXT storage boundary, independent of business JSON capacity.
MYSQL_TEXT_MAX_BYTES = 65535


def upgrade() -> None:
    for table, column in PAYLOAD_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Text(),
            type_=LONGTEXT(),
            existing_nullable=False,
        )


def downgrade() -> None:
    connection = op.get_bind()
    if (
        connection.execute(
            sa.text("SELECT 1 FROM tbl_configuration_json_revisions LIMIT 1")
        ).first()
        is not None
    ):
        raise RuntimeError(
            "Restore a backup instead of discarding "
            "configuration revision history"
        )
    for table, column in PAYLOAD_COLUMNS:
        if (
            connection.execute(
                sa.text(
                    f"SELECT 1 FROM {table} "
                    f"WHERE OCTET_LENGTH({column}) > :capacity LIMIT 1"
                ),
                {"capacity": MYSQL_TEXT_MAX_BYTES},
            ).first()
            is not None
        ):
            raise RuntimeError(
                "Encrypted JSON payloads exceed MySQL TEXT capacity"
            )
    for table, column in PAYLOAD_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=LONGTEXT(),
            type_=sa.Text(),
            existing_nullable=False,
        )
