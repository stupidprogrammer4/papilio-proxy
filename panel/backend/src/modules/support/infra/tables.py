from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.support.domain.models import (
    SupportMessageModel,
    SupportStateChangeModel,
    SupportTicketModel,
)


class SupportTicketTable(SupportTicketModel, BaseTable, table=True):
    table_name = "tbl_support_tickets"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "request_key", name="uq_support_ticket_request"
        ),
    )


class SupportMessageTable(SupportMessageModel, BaseTable, table=True):
    table_name = "tbl_support_messages"
    __table_args__ = (
        UniqueConstraint(
            "ticket_id", "request_key", name="uq_support_message_request"
        ),
    )


class SupportStateChangeTable(SupportStateChangeModel, BaseTable, table=True):
    table_name = "tbl_support_state_changes"
    __table_args__ = (
        UniqueConstraint(
            "ticket_id", "revision", name="uq_support_state_revision"
        ),
    )
