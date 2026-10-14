"""Keep meaningful SMS settlement decisions as immutable history."""

import sqlalchemy as sa
from alembic import op

revision = "0060_sms_decision_history"
down_revision = "0059_managed_provision_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_tbl_sms_settlement_decisions_sms_event_id",
        "tbl_sms_settlement_decisions",
        ["sms_event_id"],
    )
    op.drop_index("sms_event_id", table_name="tbl_sms_settlement_decisions")


def downgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT sms_event_id "
                "FROM tbl_sms_settlement_decisions "
                "GROUP BY sms_event_id HAVING COUNT(*) > 1)"
            )
        )
        .scalar_one()
    )
    if duplicate:
        raise RuntimeError("Cannot discard SMS settlement decision history")
    op.create_index(
        "sms_event_id",
        "tbl_sms_settlement_decisions",
        ["sms_event_id"],
        unique=True,
    )
    op.drop_index(
        "ix_tbl_sms_settlement_decisions_sms_event_id",
        table_name="tbl_sms_settlement_decisions",
    )
