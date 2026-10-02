from __future__ import annotations

from dataclasses import dataclass, replace

from papilio_proxy.modules.accounts.admin.domain.entities import (
    AdminFinancialSnapshot,
    AdminLogin,
    AdminOrderRow,
    AdminSession,
    AdminUserRow,
)
from papilio_proxy.modules.accounts.admin.interfaces import AdminWebRepository
from papilio_proxy.modules.analytics.dashboard.app.services import (
    DashboardService,
    DashboardSnapshot,
)
from papilio_proxy.modules.brand.profile.app.services import BrandingField, BrandingService
from papilio_proxy.modules.brand.profile.domain.entities import BotBranding
from papilio_proxy.modules.sales.pricing.app.services import PricingService, project_plan
from papilio_proxy.modules.sales.pricing.domain.entities import (
    PricingAssumptions,
    PricingProjection,
)
from papilio_proxy.modules.sales.subscriptions.app.plans import AdminPlanService
from papilio_proxy.modules.sales.subscriptions.app.services import Plan


@dataclass(slots=True)
class AdminWebService:
    repository: AdminWebRepository
    dashboard: DashboardService
    plans: AdminPlanService
    branding: BrandingService
    pricing: PricingService

    async def login(self, username: str, password: str) -> AdminLogin:
        return await self.repository.login(username, password)

    async def session(self, token: str) -> AdminSession | None:
        return await self.repository.get_session(token)

    async def logout(self, token: str) -> None:
        await self.repository.logout(token)

    async def change_password(self, username: str, current: str, new: str) -> None:
        if len(new) < 12 or new == current:
            raise ValueError("رمز جدید باید حداقل ۱۲ نویسه و متفاوت از رمز فعلی باشد.")
        await self.repository.login(username, current)
        await self.repository.set_password(username, new)

    async def overview(self) -> DashboardSnapshot:
        return await self.dashboard.snapshot()

    async def finances(self) -> AdminFinancialSnapshot:
        return await self.repository.finances()

    async def users(self, query: str, offset: int) -> list[AdminUserRow]:
        return await self.repository.list_users(query, offset=offset)

    async def orders(self, offset: int) -> list[AdminOrderRow]:
        return await self.repository.list_orders(offset=offset)

    async def list_plans(self) -> list[Plan]:
        return await self.plans.repository.list(active_only=False)

    async def save_plan(
        self,
        *,
        code: str,
        title: str,
        traffic_gb: int,
        duration_days: int,
        price_rial: int,
        sort_order: int,
        emoji: str,
        editing: bool,
    ) -> Plan:
        return await self.plans.save_validated_plan(
            code=code,
            title=title,
            traffic_gb=traffic_gb,
            duration_days=duration_days,
            price_rial=price_rial,
            sort_order=sort_order,
            emoji=emoji,
            editing=editing,
        )

    async def set_plan_active(self, code: str, active: bool) -> Plan:
        plan = await self.plans.repository.get(code)
        if plan is None:
            raise ValueError("پلن پیدا نشد.")
        if plan.is_active != active:
            await self.plans.repository.set_active(code, active)
        return replace(plan, is_active=active)

    async def get_pricing(self) -> PricingAssumptions | None:
        return await self.pricing.get()

    async def save_pricing(self, value: PricingAssumptions) -> None:
        await self.pricing.save(value)

    async def pricing_projections(self, value: PricingAssumptions) -> list[PricingProjection]:
        plans = await self.list_plans()
        return [
            project_plan(plan, value) for plan in plans if plan.duration_days == value.period_days
        ]

    async def get_branding(self) -> BotBranding:
        return await self.branding.get()

    async def update_branding(self, field: BrandingField, value: str) -> BotBranding:
        return await self.branding.update(field, value)
