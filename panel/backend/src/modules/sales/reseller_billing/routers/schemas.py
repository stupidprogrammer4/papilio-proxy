from src.modules.network.ip_limits.domain.purchased import (
    SubscriptionIpPolicyRead,
)
from src.modules.sales.reseller_billing.domain.dtos import (
    ResellerBillingSnapshot,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.routers.schemas import SubscriptionOut


class BillingSubscriptionOut(SubscriptionOut):
    payer_customer_id: int
    reseller_id: int | None
    reseller_agreement_id: int | None
    reseller_billing: ResellerBillingSnapshot | None

    @classmethod
    def from_model(
        cls,
        item: SubscriptionModel,
        ip_policy: SubscriptionIpPolicyRead | None = None,
    ) -> "BillingSubscriptionOut":
        return cls(
            **SubscriptionOut.from_model(item, ip_policy).model_dump(),
            payer_customer_id=item.payer_customer_id or item.customer_id,
            reseller_id=item.reseller_id,
            reseller_agreement_id=item.reseller_agreement_id,
            reseller_billing=ResellerBillingSnapshot.model_validate_json(
                item.reseller_billing_json
            )
            if item.reseller_billing_json is not None
            else None,
        )
