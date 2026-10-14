<script setup lang="ts">
import { computed } from "vue";
import type { IpPolicyTransitionRead } from "@papilio/api";
import { faDate } from "@papilio/ui";
import { ipAllowanceText } from "./policy";
import { useI18n } from "vue-i18n";

const props = defineProps<{ transition: IpPolicyTransitionRead }>();
const { t } = useI18n();
function allowance(): string {
  return ipAllowanceText(props.transition.target_policy, {
    none: t("ipPolicySummary.allowance.none"), unlimited: t("ipPolicySummary.allowance.unlimited"), invalid: t("ipPolicySummary.allowance.invalid"),
    one: t("ipPolicySummary.allowance.one"), many: count => t("ipPolicySummary.allowance.many", { count }),
  });
}
const reasons = computed<Record<IpPolicyTransitionRead["reason"], string>>(() => ({
  ip_policy_draining: t("ipPolicyTransition.reasons.draining"),
  legacy_lease_history_unknown: t("ipPolicyTransition.reasons.legacy"),
  closed_receipts_unavailable: t("ipPolicyTransition.reasons.receipts"),
}));
</script>

<template>
  <section class="hint-box form-grid" :aria-label="t('ipPolicyTransition.region')" aria-live="polite">
    <div class="detail-line"><span>{{ t('ipPolicyTransition.requested') }}</span><strong>{{ allowance() }}</strong></div>
    <div class="detail-line"><span>{{ t('ipPolicyTransition.status') }}</span><strong>{{ transition.status === 'draining' ? t('ipPolicyTransition.draining') : t('ipPolicyTransition.blocked') }}</strong></div>
    <p class="subtitle">{{ reasons[transition.reason] }}</p>
    <div v-if="transition.retry_at" class="detail-line"><span>{{ t('ipPolicyTransition.retryAt') }}</span><strong>{{ faDate(transition.retry_at) }}</strong></div>
    <p v-if="transition.mode === 'drain_leases'" class="subtitle">{{ t('ipPolicyTransition.drainNote') }}</p>
    <p v-else class="subtitle">{{ t('ipPolicyTransition.receiptsNote') }}</p>
    <p class="subtitle">{{ t('ipPolicyTransition.pendingNote') }}</p>
    <p class="message">{{ t('ipPolicyTransition.pausedNote') }}</p>
  </section>
</template>
