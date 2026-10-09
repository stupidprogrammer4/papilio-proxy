"""Allow independent subscription volume and time limits."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_plan_limits"
down_revision: str | None = "0036_openvpn_management_sockets"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LIMIT_COLUMNS = (
    ("tbl_plans", "quota_bytes", sa.BigInteger()),
    ("tbl_plans", "duration_days", sa.Integer()),
    ("tbl_subscriptions", "quota_bytes", sa.BigInteger()),
    ("tbl_subscriptions", "base_quota_bytes", sa.BigInteger()),
    ("tbl_subscriptions", "duration_days", sa.Integer()),
    ("tbl_subscriptions", "expires_at", sa.DateTime()),
)


def upgrade() -> None:
    for table, column, kind in LIMIT_COLUMNS:
        op.alter_column(table, column, existing_type=kind, nullable=True)


def downgrade() -> None:
    connection = op.get_bind()
    for table, column, _ in LIMIT_COLUMNS:
        missing = connection.execute(
            sa.text(f"SELECT 1 FROM {table} WHERE {column} IS NULL LIMIT 1")
        ).first()
        if missing is not None:
            raise RuntimeError("Independent plan limits require this schema")
    for table, column, kind in LIMIT_COLUMNS:
        op.alter_column(table, column, existing_type=kind, nullable=False)
