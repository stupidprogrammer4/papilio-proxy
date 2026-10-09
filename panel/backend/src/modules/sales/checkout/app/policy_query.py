from src.config.settings import PapilioSettings
from src.modules.operations.preferences.interfaces import IPreferencesService
from src.modules.sales.checkout.app.errors import checkout_conflict
from src.modules.sales.checkout.domain.contracts import PurchaseCheckoutPolicy


class PurchaseCheckoutPolicyQuery:
    def __init__(
        self, preferences: IPreferencesService, settings: PapilioSettings
    ) -> None:
        self.preferences, self.settings = preferences, settings

    async def current(self, *, locked: bool = False) -> PurchaseCheckoutPolicy:
        capacity = self.settings.purchase_intents
        if capacity is None:
            return PurchaseCheckoutPolicy()
        values = (await self.preferences.current(locked=locked)).values
        policy = values.purchase_checkout or capacity.policy
        if (
            not capacity.minimum_expiry_seconds
            <= policy.default_expiry_seconds
            <= capacity.maximum_expiry_seconds
        ):
            raise checkout_conflict("purchase_checkout_capacity", 0)
        return policy
