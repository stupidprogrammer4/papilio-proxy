<script setup lang="ts">
import type { ResellerPolicy } from "@papilio/api";
import { useI18n } from "vue-i18n";
import NumField from "@papilio/ui/NumField.vue";
const policy = defineModel<ResellerPolicy>({ required: true });
const { t } = useI18n();
defineProps<{ disabled?: boolean }>();
const capacities = [
  { key: "customer_capacity", label: "resellerPolicy.customerCapacity" },
  { key: "account_capacity", label: "resellerPolicy.teamCapacity" },
  { key: "plan_capacity", label: "resellerPolicy.planCapacity" },
  { key: "max_sessions_per_account", label: "resellerPolicy.sessionsCapacity" },
] as const;
const flags = [
  { key: "require_active_owner", label: "resellerPolicy.requireOwner" },
  { key: "customer_creation_enabled", label: "resellerPolicy.customerCreation" },
  { key: "customer_access_override_enabled", label: "resellerPolicy.customerAccessOverride" },
  { key: "customer_self_purchase", label: "resellerPolicy.customerWalletPurchase" },
  { key: "customer_can_disable_reseller_renewal", label: "resellerPolicy.disableResellerRenewal" },
] as const;
function number(key: typeof capacities[number]["key"], value: string): void {
  policy.value = { ...policy.value, [key]: Number(value) };
}
</script>
<template>
  <fieldset :disabled="disabled" class="form-grid policy-fields">
    <legend>{{t("resellerPolicy.title")}}</legend>
    <label v-for="field in flags" :key="field.key" class="check-row"><input v-model="policy[field.key]" type="checkbox"/>{{t(field.label)}}</label>
    <NumField v-for="field in capacities" :key="field.key" :label="t(field.label)" :model-value="String(policy[field.key])" @update:model-value="number(field.key, $event)"/>
    <label class="field"><span>{{t("resellerPolicy.sessionCapacityReached")}}</span><select :aria-label="t('resellerPolicy.sessionCapacityReached')" v-model="policy.session_limit_mode"><option value="reject_new">{{t("resellerPolicy.rejectNew")}}</option><option value="replace_oldest">{{t("resellerPolicy.replaceOldest")}}</option></select></label>
    <label class="field"><span>{{t("resellerPolicy.payingWallet")}}</span><select :aria-label="t('resellerPolicy.payingWallet')" v-model="policy.payer_mode"><option value="reseller_wallet">{{t("resellerPolicy.resellerWallet")}}</option><option value="customer_wallet">{{t("resellerPolicy.customerWallet")}}</option><option value="either">{{t("resellerPolicy.eitherWallet")}}</option></select></label>
    <label class="field"><span>{{t("resellerPolicy.renewalPrice")}}</span><select :aria-label="t('resellerPolicy.renewalPrice')" v-model="policy.renewal_price_mode"><option value="purchase_snapshot">{{t("resellerPolicy.purchasePrice")}}</option><option value="current_agreement">{{t("resellerPolicy.agreementPrice")}}</option></select></label>
    <label class="field"><span>{{t("resellerPolicy.planEligibility")}}</span><select :aria-label="t('resellerPolicy.planEligibility')" v-model="policy.renewal_availability_mode"><option value="purchase_snapshot">{{t("resellerPolicy.purchaseEligibility")}}</option><option value="current_agreement">{{t("resellerPolicy.requireActiveAgreement")}}</option></select></label>
    <p class="hint-box">{{t("resellerPolicy.renewalHint")}}</p>
    <h3>{{t("resellerPolicy.initialAccess")}}</h3>
    <label class="check-row"><input v-model="policy.new_customer_access.is_active" type="checkbox"/>{{t("resellerPolicy.accountEnabled")}}</label>
    <label class="check-row"><input v-model="policy.new_customer_access.services_enabled" type="checkbox"/>{{t("resellerPolicy.serviceAccess")}}</label>
    <label class="check-row"><input v-model="policy.new_customer_access.renewals_enabled" type="checkbox"/>{{t("resellerPolicy.renewalAccess")}}</label>
  </fieldset>
</template>
<style scoped>.policy-fields { border:1px solid var(--line); border-radius:12px; padding:16px; }</style>
