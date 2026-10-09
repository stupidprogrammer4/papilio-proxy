from src.config.settings import PapilioSettings
from src.modules.billing.destinations.domain.dtos import CheckoutPolicy
from src.modules.operations.preferences.interfaces import IPreferencesService


class CheckoutFundingQuery:
    """Expose current owning topup policy without implying settlement."""

    def __init__(
        self, preferences: IPreferencesService, settings: PapilioSettings
    ) -> None:
        self.preferences, self.settings = preferences, settings

    async def policy(self) -> CheckoutPolicy:
        current = await self.preferences.current()
        return current.values.checkout or self.settings.checkout.policy
