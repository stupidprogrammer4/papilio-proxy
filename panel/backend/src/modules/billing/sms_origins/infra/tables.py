from papilio.infra.db.table import BaseTable
from sqlalchemy import UniqueConstraint

from src.modules.billing.sms_origins.domain.models import (
    ReceivingAliasModel,
    ReceivingRealmModel,
    SmsOriginAdmissionModel,
    SmsParserProfileModel,
    SmsParserRevisionModel,
    SmsSettlementClaimModel,
    SmsSettlementDecisionModel,
    SmsSettlementModel,
)


class ReceivingRealmTable(ReceivingRealmModel, BaseTable, table=True):
    pass


class ReceivingAliasTable(ReceivingAliasModel, BaseTable, table=True):
    pass


class SmsParserProfileTable(SmsParserProfileModel, BaseTable, table=True):
    pass


class SmsParserRevisionTable(SmsParserRevisionModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint("profile_id", "revision", name="uq_sms_parser_rev"),
    )


class SmsSettlementTable(SmsSettlementModel, BaseTable, table=True):
    pass


class SmsSettlementClaimTable(SmsSettlementClaimModel, BaseTable, table=True):
    __table_args__ = (
        UniqueConstraint(
            "identity_kind", "identity_key", name="uq_sms_settlement_identity"
        ),
    )


class SmsOriginAdmissionTable(SmsOriginAdmissionModel, BaseTable, table=True):
    pass


class SmsSettlementDecisionTable(
    SmsSettlementDecisionModel, BaseTable, table=True
):
    pass
