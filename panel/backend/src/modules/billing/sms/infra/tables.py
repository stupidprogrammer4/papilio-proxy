from papilio.infra.db.table import BaseTable
from sqlalchemy import Index

from src.modules.billing.sms.domain.models import SmsEventModel


class SmsEventTable(SmsEventModel, BaseTable, table=True):
    __table_args__ = (Index("ix_sms_amount_time", "amount_rial", "sent_at"),)
