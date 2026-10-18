"""Expand audited preference payload capacity for the bot message catalog."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "0067_pref_catalog_capacity"
down_revision = "0066_topup_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "tbl_preferences_revisions",
        "values_json",
        existing_type=sa.Text(),
        type_=LONGTEXT(),
        existing_nullable=False,
    )


def downgrade() -> None:
    result = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM tbl_preferences_revisions "
            "WHERE OCTET_LENGTH(values_json) > 65535 LIMIT 1"
        )
    )
    if result.first() is not None:
        raise RuntimeError(
            "Preference data exceeds TEXT capacity; restore a backup "
            "instead of downgrading."
        )
    op.alter_column(
        "tbl_preferences_revisions",
        "values_json",
        existing_type=LONGTEXT(),
        type_=sa.Text(),
        existing_nullable=False,
    )
