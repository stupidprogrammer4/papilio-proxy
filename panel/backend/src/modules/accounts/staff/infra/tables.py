from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.accounts.staff.domain.models import (
    StaffGrantModel,
    StaffModel,
    StaffSessionModel,
)
from src.modules.accounts.staff.domain.roles import (
    RoleModel,
    RoleRevisionModel,
    StaffRoleChangeModel,
    StaffRoleModel,
)


class StaffTable(StaffModel, BaseTable, table=True):
    table_name = "tbl_staff"


class StaffGrantTable(StaffGrantModel, BaseTable, table=True):
    table_name = "tbl_staff_grants"


class StaffSessionTable(StaffSessionModel, BaseTable, table=True):
    table_name = "tbl_staff_sessions"


class RoleTable(RoleModel, BaseTable, table=True):
    table_name = "tbl_staff_roles"


class RoleRevisionTable(RoleRevisionModel, BaseTable, table=True):
    table_name = "tbl_staff_role_revisions"
    __table_args__ = (
        UniqueConstraint("role_id", "revision", name="uq_staff_role_revision"),
    )


class StaffRoleTable(StaffRoleModel, BaseTable, table=True):
    table_name = "tbl_staff_role_memberships"


class StaffRoleChangeTable(StaffRoleChangeModel, BaseTable, table=True):
    table_name = "tbl_staff_role_changes"
