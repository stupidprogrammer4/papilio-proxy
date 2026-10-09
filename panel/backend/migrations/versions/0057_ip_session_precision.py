"""Preserve the exact expiry of issued IP leases and bans."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0057_ip_session_precision"
down_revision = "0056_ip_lease_transitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "tbl_ip_sessions",
        "first_seen_at",
        existing_type=sa.DateTime(),
        type_=DATETIME(fsp=6),
        existing_nullable=False,
    )
    op.alter_column(
        "tbl_ip_sessions",
        "last_seen_at",
        existing_type=sa.DateTime(),
        type_=DATETIME(fsp=6),
        existing_nullable=False,
    )
    op.alter_column(
        "tbl_ip_sessions",
        "expires_at",
        existing_type=sa.DateTime(),
        type_=DATETIME(fsp=6),
        existing_nullable=False,
    )
    op.alter_column(
        "tbl_ip_sessions",
        "blocked_until",
        existing_type=sa.DateTime(),
        type_=DATETIME(fsp=6),
        existing_nullable=True,
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM tbl_ip_sessions")):
        raise RuntimeError(
            "Downgrade would lose exact IP lease or ban deadlines"
        )
    op.alter_column(
        "tbl_ip_sessions",
        "first_seen_at",
        existing_type=DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
    )
    op.alter_column(
        "tbl_ip_sessions",
        "last_seen_at",
        existing_type=DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
    )
    op.alter_column(
        "tbl_ip_sessions",
        "expires_at",
        existing_type=DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
    )
    op.alter_column(
        "tbl_ip_sessions",
        "blocked_until",
        existing_type=DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=True,
    )
