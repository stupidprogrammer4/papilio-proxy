<script setup lang="ts">
import type { FulfillmentPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
const policy = defineModel<FulfillmentPolicy>({ required: true });
const fields = [
  { key: "minimum_successes", label: "plans.fulfillment.minimumSuccesses" },
  { key: "max_attempts", label: "plans.fulfillment.maxAttempts" },
  { key: "claim_seconds", label: "plans.fulfillment.claimSeconds" },
  { key: "retry_seconds", label: "plans.fulfillment.retrySeconds" },
  { key: "deadline_minutes", label: "plans.fulfillment.deadlineMinutes" },
] as const;
function number(key: typeof fields[number]["key"], value: string): void { policy.value = { ...policy.value, [key]: Number(value) }; }
</script>
<template>
  <div class="form-grid">
    <label class="check-row"><input v-model="policy.automatic" type="checkbox" />{{ t("plans.fulfillment.automatic") }}</label>
    <label class="field"><span>{{ t("plans.fulfillment.activation") }}</span><select v-model="policy.activation"><option value="all">{{ t("plans.fulfillment.all") }}</option><option value="any">{{ t("plans.fulfillment.any") }}</option><option value="quorum">{{ t("plans.fulfillment.quorum") }}</option></select></label>
    <NumField v-for="field in fields" :key="field.key" :model-value="String(policy[field.key])" :label="t(field.label)" @update:model-value="number(field.key, $event)" />
    <label class="field"><span>{{ t("plans.fulfillment.periodStart") }}</span><select v-model="policy.expiry_start"><option value="activation">{{ t("plans.fulfillment.onActivation") }}</option><option value="purchase">{{ t("plans.fulfillment.onPurchase") }}</option></select></label>
    <label class="field"><span>{{ t("plans.fulfillment.afterDeadline") }}</span><select v-model="policy.failure_action"><option value="hold">{{ t("plans.fulfillment.hold") }}</option><option value="refund_wallet">{{ t("plans.fulfillment.refundWallet") }}</option></select></label>
    <label class="field"><span>{{ t("plans.fulfillment.renewalTrigger") }}</span><select v-model="policy.renewal_trigger"><option value="expiry">{{ t("plans.fulfillment.expiry") }}</option><option value="quota">{{ t("plans.fulfillment.quota") }}</option><option value="either">{{ t("plans.fulfillment.either") }}</option></select></label>
    <label class="field"><span>{{ t("plans.fulfillment.renewalQuota") }}</span><select v-model="policy.renewal_quota"><option value="reset">{{ t("plans.fulfillment.reset") }}</option><option value="carry_unused">{{ t("plans.fulfillment.carryUnused") }}</option></select></label>
    <label class="field"><span>{{ t("plans.fulfillment.renewalPrice") }}</span><select v-model="policy.renewal_price"><option value="purchased">{{ t("plans.fulfillment.purchasedPrice") }}</option><option value="current_plan">{{ t("plans.fulfillment.currentPlanPrice") }}</option></select></label>
  </div>
</template>
