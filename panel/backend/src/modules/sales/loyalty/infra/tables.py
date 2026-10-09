from papilio.infra.db.table import BaseTable

from src.modules.sales.loyalty.domain.models import (
    CustomerTierModel,
    LoyaltyPolicyModel,
    PurchaseVolumeModel,
)


class CustomerTierTable(CustomerTierModel, BaseTable, table=True):
    pass


class LoyaltyPolicyTable(LoyaltyPolicyModel, BaseTable, table=True):
    pass


class PurchaseVolumeTable(PurchaseVolumeModel, BaseTable, table=True):
    pass
