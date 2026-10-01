from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from bot.models.admin_web import (
    AdminFinancialSnapshot,
    AdminLogin,
    AdminOrderRow,
    AdminPaymentRow,
    AdminSession,
    AdminUserRow,
)
from bot.models.branding import BotBranding
from bot.models.pricing import PricingAssumptions, PricingProjection
from bot.services.admin_plans import AdminPlanService
from bot.services.branding import BrandingField, BrandingService
from bot.services.dashboard import DashboardService, DashboardSnapshot
from bot.services.pricing import PricingService, project_plan
from bot.services.subscriptions import Plan


class AdminWebRepository(Protocol):
    async def login(self, username: str, password: str) -> AdminLogin: ...
    async def get_session(self, token: str) -> AdminSession | None: ...
    async def logout(self, token: str) -> None: ...
    async def set_password(self, username: str, password: str) -> None: ...
    async def finances(self) -> AdminFinancialSnapshot: ...
    async def list_users(self, query: str = "", *, limit: int = 50, offset: int = 0) -> list[AdminUserRow]: ...
    async def list_orders(self, *, limit: int = 50, offset: int = 0) -> list[AdminOrderRow]: ...
    async def list_payments(self, *, limit: int = 50, offset: int = 0) -> list[AdminPaymentRow]: ...


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

    async def payments(self, offset: int) -> list[AdminPaymentRow]:
        return await self.repository.list_payments(offset=offset)

    async def list_plans(self) -> list[Plan]:
        return await self.plans.repository.list(active_only=False)

    async def save_plan(
        self, *, code: str, title: str, traffic_gb: int, duration_days: int,
        price_rial: int, sort_order: int, emoji: str, editing: bool,
    ) -> Plan:
        return await self.plans.save_validated_plan(
            code=code, title=title, traffic_gb=traffic_gb, duration_days=duration_days,
            price_rial=price_rial, sort_order=sort_order, emoji=emoji, editing=editing,
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
        return [project_plan(plan, value) for plan in plans
                if plan.duration_days == value.period_days]

    async def get_branding(self) -> BotBranding:
        return await self.branding.get()

    async def update_branding(self, field: BrandingField, value: str) -> BotBranding:
        return await self.branding.update(field, value)
