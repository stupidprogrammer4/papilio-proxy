<script setup lang="ts">
import type { IpLimitChoice, PlanIpPolicyRead } from "@papilio/api";
import { useI18n } from "vue-i18n";

defineProps<{ policy?: PlanIpPolicyRead | null; configured?: IpLimitChoice | null }>();
const { t } = useI18n();
function allowanceText(policy: IpLimitChoice | null | undefined): string {
  if (!policy) return t("plans.ip.noRestriction");
  if (!policy.enabled) return t("plans.ip.unlimited");
  if (!Number.isSafeInteger(policy.max_ips) || policy.max_ips <= 0) return t("plans.ip.invalid");
  if (policy.max_ips === 1) return t("plans.ip.one");
  return t("plans.ip.upTo", { count: policy.max_ips });
}
</script>

<template>
  <section class="hint-box form-grid" :aria-label="t('plans.ip.allowance')">
    <div class="detail-line"><span>{{ t("plans.ip.allowance") }}</span><strong>{{ policy || configured ? allowanceText(policy?.policy ?? configured) : t("plans.ip.apiUnavailable") }}</strong></div>
    <p v-if="policy" class="subtitle">{{ t(policy.source === "plan_override" ? "plans.explicitTerms" : "plans.ip.purchaseDefaults") }}. {{ t("plans.ip.captured") }}</p>
    <p v-else class="subtitle">{{ t("plans.ip.refreshOffer") }}</p>
    <p class="subtitle">{{ t("plans.ip.apiOnly") }}</p>
  </section>
</template>
