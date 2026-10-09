from papilio.errors.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnAuthorizedException,
    ValidationException,
)

from src.config.settings import PapilioSettings, ResellerSettings
from src.modules.accounts.resellers.domain.dtos import (
    ResellerPolicy,
    ResellerScopes,
)
from src.modules.accounts.resellers.domain.models import (
    ResellerAccountModel,
    ResellerModel,
)
from src.modules.accounts.resellers.domain.results import ResellerPrincipal
from src.modules.accounts.staff.domain.results import StaffAccess


class ResellerCapacity:
    @staticmethod
    def configured(settings: PapilioSettings) -> ResellerSettings:
        result = settings.resellers
        if result is None:
            raise conflict("reseller_disabled")
        return result

    @staticmethod
    def valid(policy: ResellerPolicy, settings: ResellerSettings) -> bool:
        return (
            policy.customer_capacity <= settings.max_customers_per_reseller
            and policy.account_capacity <= settings.max_accounts_per_reseller
            and policy.plan_capacity <= settings.max_plans_per_reseller
            and policy.max_sessions_per_account
            <= settings.max_sessions_per_account
        )

    @classmethod
    def validate(
        cls, policy: ResellerPolicy, settings: ResellerSettings
    ) -> None:
        if not cls.valid(policy, settings):
            raise ValidationException(
                message="سیاست نمایندگی از ظرفیت عملیاتی بیشتر است.",
                message_code="reseller_policy_capacity",
                loc=["policy"],
                input=policy.model_dump(),
            )

    @staticmethod
    def scopes(scopes: ResellerScopes, settings: ResellerSettings) -> None:
        if len(scopes.scopes) > settings.max_scopes_per_account:
            raise ValidationException(
                message="تعداد دسترسی‌ها از ظرفیت نمایندگی بیشتر است.",
                message_code="reseller_scope_capacity",
                loc=["scopes"],
                input=len(scopes.scopes),
            )


class ResellerDelegation:
    @staticmethod
    def principal(
        reseller: ResellerModel,
        account: ResellerAccountModel | None,
        principal: ResellerPrincipal,
        scope: str,
        settings: PapilioSettings,
    ) -> frozenset[str]:
        capacity = settings.resellers
        if (
            capacity is None
            or not capacity.enabled
            or principal.reseller_id != reseller.id
            or not reseller.login_enabled
            or reseller.access_revision != principal.reseller_access_revision
            or account is None
            or not account.is_active
            or account.id != principal.account_id
            or account.reseller_id != reseller.id
            or account.revision != principal.account_revision
        ):
            raise denied()
        scopes = ResellerScopes.model_validate_json(account.scopes_json)
        if not set(scopes.scopes) & {"*", scope}:
            raise ForbiddenException(
                message="دسترسی به این بخش نمایندگی مجاز نیست.",
                message_code="reseller_scope_denied",
            )
        return frozenset(scopes.scopes)

    @staticmethod
    def staff(actor: StaffAccess | None, level: str) -> None:
        if (
            actor is None
            or not actor.staff.is_active
            or not actor.effective_scopes
            & {"*", "resellers:*", f"resellers:{level}"}
        ):
            raise ForbiddenException(
                message="مدیریت این نمایندگی مجاز نیست.",
                message_code="reseller_staff_scope_denied",
            )

    @staticmethod
    def verify(actor: frozenset[str], requested: list[str]) -> None:
        if "*" not in actor and not set(requested) <= actor:
            raise ForbiddenException(
                message="واگذاری این دسترسی‌های نمایندگی مجاز نیست.",
                message_code="reseller_delegation_denied",
            )


def conflict(code: str) -> ConflictException:
    return ConflictException(
        message="عملیات نمایندگی در وضعیت فعلی مجاز نیست.",
        message_code=code,
        unique_dict={},
    )


def missing(entity: str, id: int) -> NotFoundException:
    return NotFoundException(
        message="رکورد نمایندگی پیدا نشد.",
        message_code="reseller_not_found",
        entity=entity,
        identifier="id",
        identifier_value=id,
    )


def denied() -> UnAuthorizedException:
    return UnAuthorizedException(
        message="نشست نمایندگی معتبر نیست.",
        message_code="reseller_unauthorized",
    )
