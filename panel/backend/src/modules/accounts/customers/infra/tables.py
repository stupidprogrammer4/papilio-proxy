from papilio.infra.db.table import BaseTable
from sqlalchemy import Index

from src.modules.accounts.customers.domain.models import (
    CustomerAccessChangeModel,
    CustomerModel,
)


class CustomerTable(CustomerModel, BaseTable, table=True):
    __table_args__ = (
        Index("ix_customer_services_enabled", "services_enabled", "id"),
        Index(
            "ix_customer_hold_pending",
            "service_hold_pending",
            "service_hold_at",
            "id",
        ),
    )


class CustomerAccessChangeTable(
    CustomerAccessChangeModel, BaseTable, table=True
):
    table_name = "tbl_customer_access_changes"
