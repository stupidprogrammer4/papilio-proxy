from __future__ import annotations

import re
from dataclasses import dataclass, replace
from unicodedata import category

from papilio_proxy.modules.sales.subscriptions.app.services import (
    Plan,
    PlanRepository,
    UnknownPlanError,
)


class AdminAccessError(PermissionError):
    """The Telegram user is not allowed to manage plans."""


class PlanValidationError(ValueError):
    """Plan input cannot be stored safely."""


@dataclass(slots=True)
class AdminPlanService:
    """Admin-only plan operations backed by the shared plan repository."""

    repository: PlanRepository
    admin_ids: frozenset[int]

    def _authorize(self, telegram_id: int) -> None:
        if telegram_id not in self.admin_ids:
            raise AdminAccessError("دسترسی مدیریت پلن‌ها مجاز نیست.")

    async def list_plans(self, telegram_id: int) -> list[Plan]:
        self._authorize(telegram_id)
        return await self.repository.list(active_only=False)

    async def get_plan(self, telegram_id: int, code: str) -> Plan:
        self._authorize(telegram_id)
        plan = await self.repository.get(code)
        if plan is None:
            raise UnknownPlanError(code)
        return plan

    async def set_active(self, telegram_id: int, code: str, is_active: bool) -> Plan:
        self._authorize(telegram_id)
        plan = await self.get_plan(telegram_id, code)
        if plan.is_active != is_active:
            await self.repository.set_active(code, is_active)
        return replace(plan, is_active=is_active)

    async def save_plan(
        self,
        telegram_id: int,
        *,
        code: str,
        title: str,
        traffic_gb: int,
        duration_days: int,
        price_rial: int,
        sort_order: int,
        emoji: str = "🦋",
        editing: bool = False,
    ) -> Plan:
        self._authorize(telegram_id)
        return await self.save_validated_plan(
            code=code,
            title=title,
            traffic_gb=traffic_gb,
            duration_days=duration_days,
            price_rial=price_rial,
            sort_order=sort_order,
            emoji=emoji,
            editing=editing,
        )

    async def save_validated_plan(
        self,
        *,
        code: str,
        title: str,
        traffic_gb: int,
        duration_days: int,
        price_rial: int,
        sort_order: int,
        emoji: str = "🦋",
        editing: bool = False,
    ) -> Plan:
        """Validation/persistence shared by authenticated Telegram and web adapters."""
        code = code.strip()
        title = title.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", code):
            raise PlanValidationError("کد باید ۱ تا ۶۴ نویسهٔ لاتین، عدد، خط تیره یا زیرخط باشد.")
        if not 1 <= len(title) <= 100 or any(ord(char) < 32 for char in title):
            raise PlanValidationError("عنوان باید ۱ تا ۱۰۰ نویسهٔ قابل‌نمایش باشد.")
        if isinstance(traffic_gb, bool) or not 1 <= traffic_gb <= 10_000:
            raise PlanValidationError("حجم باید بین ۱ تا ۱۰٬۰۰۰ گیگابایت باشد.")
        if isinstance(duration_days, bool) or not 1 <= duration_days <= 3_650:
            raise PlanValidationError("مدت باید بین ۱ تا ۳٬۶۵۰ روز باشد.")
        if (
            isinstance(price_rial, bool)
            or not 10 <= price_rial <= 10_000_000_000_000
            or price_rial % 10
        ):
            raise PlanValidationError("قیمت ریالی باید مثبت و مضرب ۱۰ باشد.")
        if isinstance(sort_order, bool) or not -100_000 <= sort_order <= 100_000:
            raise PlanValidationError("ترتیب نمایش باید بین ۱۰۰٬۰۰۰- و ۱۰۰٬۰۰۰ باشد.")
        emoji = emoji.strip()
        if not emoji or len(emoji) > 8 or not any(category(char) == "So" for char in emoji):
            raise PlanValidationError("ایموجی باید یک نماد کوتاه و قابل‌نمایش باشد.")
        existing = await self.repository.get(code)
        if editing and existing is None:
            raise UnknownPlanError(code)
        if not editing and existing is not None:
            raise PlanValidationError("این کد قبلاً ثبت شده است؛ کد دیگری انتخاب کنید.")
        plan = Plan(
            code=code,
            title=title,
            traffic_gb=traffic_gb,
            duration_days=duration_days,
            price_rial=price_rial,
            is_active=existing.is_active if existing else False,
            sort_order=sort_order,
            emoji=emoji,
        )
        await self.repository.save(plan)
        return plan
