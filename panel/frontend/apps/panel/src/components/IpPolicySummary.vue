<script setup lang="ts">
import type { EffectiveIpPolicyRead, PurchasedIpPolicyRead } from "@papilio/api";
import { useI18n } from "vue-i18n";
import { useLocalizedFormats } from "../composables/useLocalizedFormats";
import { ipAllowanceText } from "./ipLimits/policy";
import IpPolicyTransition from "./ipLimits/IpPolicyTransition.vue";

defineProps<{ purchased?: PurchasedIpPolicyRead | null; effective?: EffectiveIpPolicyRead; compact?: boolean }>();
const { t } = useI18n();
const { date } = useLocalizedFormats();
const sources: Record<string, string> = { subscription_override: "subscriptionOverride", purchased_snapshot: "purchasedSnapshot", legacy_unrestricted: "legacyUnrestricted" };
function allowance(policy: Parameters<typeof ipAllowanceText>[0]): string {
  return ipAllowanceText(policy, {
    none: t("ipPolicySummary.allowance.none"), unlimited: t("ipPolicySummary.allowance.unlimited"), invalid: t("ipPolicySummary.allowance.invalid"),
    one: t("ipPolicySummary.allowance.one"), many: count => t("ipPolicySummary.allowance.many", { count }),
  });
}
</script>

<template>
  <section :aria-label="t('ipPolicySummary.region')" :class="compact ? 'form-grid' : 'hint-box form-grid'">
    <div class="detail-line"><span>{{ t("ipPolicySummary.purchased") }}</span><strong>{{ purchased ? allowance(purchased.policy) : purchased === null ? t('ipPolicySummary.legacyNoSnapshot') : t('ipPolicySummary.unavailable') }}</strong></div>
    <template v-if="purchased && !compact"><p class="subtitle">{{ t("ipPolicySummary.captured", { date: date(purchased.captured_at) }) }} · {{t(purchased.source==='plan_override'?'ipPolicySummary.explicitPlan':'ipPolicySummary.purchaseDefaults')}}<span v-if="purchased.plan_id!==null"> · {{ t("ipPolicySummary.plan", { id: purchased.plan_id }) }}</span></p></template>
    <div v-if="effective" class="detail-line"><span>{{ t("ipPolicySummary.current") }}</span><strong>{{allowance(effective.policy)}}</strong></div>
    <p v-if="effective" class="subtitle">{{t(`ipPolicySummary.sources.${sources[effective.source]}`)}} · {{ t('ipPolicySummary.sharedScope') }}</p>
    <p v-if="effective?.source==='subscription_override'" class="subtitle">{{ t("ipPolicySummary.overrideNote") }}</p>
    <IpPolicyTransition v-if="effective?.transition" :transition="effective.transition" />
    <p class="message">{{ t("ipPolicySummary.apiOnly") }}</p>
  </section>
</template>
