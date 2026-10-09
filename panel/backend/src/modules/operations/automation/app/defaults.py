from src.config.settings import PapilioSettings
from src.modules.operations.automation.domain.dtos import (
    ScheduleKey,
    ScheduleMode,
    SchedulePolicy,
)
from src.modules.operations.automation.domain.models import (
    AutomationRegistrationModel,
)
from src.modules.operations.automation.domain.results import AutomationSchedule


class AutomationDefaults:
    def __init__(self, settings: PapilioSettings) -> None:
        self.settings = settings

    def policies(self) -> dict[ScheduleKey, tuple[str, SchedulePolicy]]:
        p = self.settings.operations
        choices = {
            ScheduleKey.NOTIFICATIONS: (
                "notifications",
                self.settings.notifications.scan_cron,
                self.settings.notifications.batch_size,
                None,
            ),
            ScheduleKey.CUSTOMER_HOLDS: (
                "subscriptions",
                p.customer_hold_scan_cron,
                p.customer_hold_batch_size,
                None,
            ),
            ScheduleKey.LIFECYCLE: (
                "subscriptions",
                p.lifecycle_scan_cron,
                p.lifecycle_batch_size,
                None,
            ),
            ScheduleKey.PROVISIONING: (
                "subscriptions",
                self.settings.fulfillment.scan_cron,
                self.settings.fulfillment.batch_size,
                self.settings.fulfillment.recheck_seconds,
            ),
            ScheduleKey.PAYMENTS: (
                "payments",
                p.payment_scan_cron,
                p.payment_batch_size,
                p.payment_recheck_seconds,
            ),
            ScheduleKey.NODES: (
                "network",
                p.node_health_scan_cron,
                p.node_health_batch_size,
                p.node_health_recheck_seconds,
            ),
            ScheduleKey.ATTENTION: (
                "subscriptions",
                p.subscription_attention_scan_cron,
                p.subscription_attention_batch_size,
                p.subscription_attention_recheck_seconds,
            ),
            ScheduleKey.RENEWALS: (
                "subscriptions",
                p.renewal_scan_cron,
                p.renewal_batch_size,
                None,
            ),
        }
        checkout = self.settings.purchase_intents
        choices[ScheduleKey.CHECKOUT] = (
            "subscriptions",
            checkout.scan_cron
            if checkout is not None
            else p.automation_registration_cron,
            checkout.scan_limit
            if checkout is not None
            else p.automation_max_batch_size,
            checkout.recheck_seconds if checkout is not None else None,
        )
        runtime = self.settings.core_runtime
        choices[ScheduleKey.CORE_RUNTIME] = (
            "network",
            runtime.scan_cron
            if runtime is not None
            else p.automation_registration_cron,
            runtime.scan_batch_size
            if runtime is not None
            else p.automation_max_batch_size,
            None,
        )
        provisioning = self.settings.core_provisioning
        choices[ScheduleKey.CORE_PROVISIONING] = (
            "network",
            provisioning.scan_cron
            if provisioning is not None
            else p.automation_registration_cron,
            provisioning.batch_size
            if provisioning is not None
            else p.automation_max_batch_size,
            None,
        )
        return {
            key: (
                scope,
                SchedulePolicy(
                    mode=ScheduleMode(p.automation_default_mode),
                    interval_seconds=p.automation_default_interval_seconds
                    if p.automation_default_mode == ScheduleMode.INTERVAL
                    else None,
                    enabled=p.automation_enabled
                    and (key != ScheduleKey.CHECKOUT or checkout is not None)
                    and (
                        key != ScheduleKey.CORE_RUNTIME
                        or runtime is not None
                        and runtime.enabled
                    )
                    and (
                        key != ScheduleKey.CORE_PROVISIONING
                        or provisioning is not None
                        and provisioning.mode != "disabled"
                        and runtime is not None
                        and runtime.enabled
                    ),
                    cron=cron
                    if p.automation_default_mode == ScheduleMode.CRON
                    else None,
                    timezone=p.automation_timezone
                    if p.automation_default_mode == ScheduleMode.CRON
                    else None,
                    batch_size=batch,
                    recheck_seconds=recheck,
                ),
            )
            for key, (scope, cron, batch, recheck) in choices.items()
        }

    def schedule(self, key: ScheduleKey) -> AutomationSchedule:
        scope, values = self.policies()[key]
        return AutomationSchedule(
            key, scope, values, 0, None, None, self.capacity_accepts(values)
        )

    def capacity_accepts(self, values: SchedulePolicy) -> bool:
        capacity = self.settings.operations
        return (
            values.batch_size <= capacity.automation_max_batch_size
            and (
                values.recheck_seconds is None
                or values.recheck_seconds
                <= capacity.automation_max_recheck_seconds
            )
            and (
                values.interval_seconds is None
                or capacity.automation_min_interval_seconds
                <= values.interval_seconds
                <= capacity.automation_max_interval_seconds
            )
        )

    def registration_view(
        self, key: ScheduleKey, row: AutomationRegistrationModel | None
    ) -> AutomationSchedule:
        fallback = self.schedule(key)
        if row is None:
            return fallback
        values = SchedulePolicy.model_validate_json(row.policy_json)
        return AutomationSchedule(
            key,
            fallback.scope,
            values,
            row.revision,
            row.applied_revision,
            row.registered_at,
            self.capacity_accepts(values),
        )
