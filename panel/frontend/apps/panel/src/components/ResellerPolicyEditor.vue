<script setup lang="ts">
import type { ResellerPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
const policy = defineModel<ResellerPolicy>({ required: true });
defineProps<{ disabled?: boolean }>();
const capacities = [
  { key: "customer_capacity", label: "Capacity Customers" },
  { key: "account_capacity", label: "Team account capacity" },
  { key: "plan_capacity", label: "Plan agreement capacity" },
  { key: "max_sessions_per_account", label: "Sessions per account" },
] as const;
const flags = [
  { key: "require_active_owner", label: "Require an active reseller owner" },
  { key: "customer_creation_enabled", label: "Allow customer creation" },
  { key: "customer_access_override_enabled", label: "Allow custom initial customer access" },
  { key: "customer_self_purchase", label: "Allow customers to purchase with their own wallets" },
  { key: "customer_can_disable_reseller_renewal", label: "Allow customers to disable reseller-funded renewal" },
] as const;
function number(key: typeof capacities[number]["key"], value: string): void {
  policy.value = { ...policy.value, [key]: Number(value) };
}
</script>
<template>
  <fieldset :disabled="disabled" class="form-grid policy-fields">
    <legend>Reseller policy</legend>
    <label v-for="field in flags" :key="field.key" class="check-row"><input v-model="policy[field.key]" type="checkbox" />{{ field.label }}</label>
    <NumField v-for="field in capacities" :key="field.key" :label="field.label" :model-value="String(policy[field.key])" @update:model-value="number(field.key, $event)" />
    <label class="field"><span>When session capacity is reached</span><select aria-label="When session capacity is reached" v-model="policy.session_limit_mode"><option value="reject_new">Reject new sign-in</option><option value="replace_oldest">Replace oldest sessions</option></select></label>
    <label class="field"><span>Allowed paying wallet</span><select aria-label="Allowed paying wallet" v-model="policy.payer_mode"><option value="reseller_wallet">Reseller wallet</option><option value="customer_wallet">Wallet Customer</option><option value="either">Explicit choice of either wallet</option></select></label>
    <label class="field"><span>Renewal price for new subscriptions</span><select aria-label="Renewal price for new subscriptions" v-model="policy.renewal_price_mode"><option value="purchase_snapshot">Purchase price snapshot</option><option value="current_agreement">Agreement price at renewal</option></select></label>
    <label class="field"><span>Plan eligibility for renewal</span><select aria-label="Plan eligibility for renewal" v-model="policy.renewal_availability_mode"><option value="purchase_snapshot">Use purchase eligibility snapshot</option><option value="current_agreement">Require current active plan and agreement</option></select></label>
    <p class="hint-box">Renewal pricing and eligibility are recorded at purchase. Changes apply to future purchases. The reseller renewal switch applies to all its renewals.</p>
    <h3>Initial customer access</h3>
    <label class="check-row"><input v-model="policy.new_customer_access.is_active" type="checkbox" />Account enabled</label>
    <label class="check-row"><input v-model="policy.new_customer_access.services_enabled" type="checkbox" />Service access</label>
    <label class="check-row"><input v-model="policy.new_customer_access.renewals_enabled" type="checkbox" />Renewal access</label>
  </fieldset>
</template>
<style scoped>.policy-fields { border:1px solid var(--line); border-radius:12px; padding:16px; }</style>
