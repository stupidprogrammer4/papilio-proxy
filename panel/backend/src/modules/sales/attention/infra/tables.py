from papilio.infra.db.table import BaseTable

from src.modules.sales.attention.domain.models import (
    SubscriptionAttentionModel,
)


class SubscriptionAttentionTable(
    SubscriptionAttentionModel, BaseTable, table=True
):
    table_name = "tbl_subscription_attention"
