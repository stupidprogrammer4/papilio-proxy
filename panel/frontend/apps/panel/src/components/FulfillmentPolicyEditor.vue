<script setup lang="ts">
import type { FulfillmentPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
const policy = defineModel<FulfillmentPolicy>({ required: true });
const fields = [
  { key: "minimum_successes", label: "Minimum successful configurations for quorum" },
  { key: "max_attempts", label: "Maximum apply attempts" },
  { key: "claim_seconds", label: "Node task lease (seconds)" },
  { key: "retry_seconds", label: "Retry interval (seconds)" },
  { key: "deadline_minutes", label: "Provisioning deadline (minutes)" },
] as const;
function number(key: typeof fields[number]["key"], value: string): void { policy.value = { ...policy.value, [key]: Number(value) }; }
</script>
<template>
  <div class="form-grid">
    <label class="check-row"><input v-model="policy.automatic" type="checkbox" />Prepare automatically after purchase and renewal</label>
    <label class="field"><span>Activation requirement</span><select v-model="policy.activation"><option value="all">All configurations succeed</option><option value="any">At least one configuration succeeds</option><option value="quorum">Successful configuration quorum</option></select></label>
    <NumField v-for="field in fields" :key="field.key" :model-value="String(policy[field.key])" :label="field.label" @update:model-value="number(field.key, $event)" />
    <label class="field"><span>Subscription period starts</span><select v-model="policy.expiry_start"><option value="activation">On activation</option><option value="purchase">On purchase or renewal</option></select></label>
    <label class="field"><span>After deadline or attempt limit</span><select v-model="policy.failure_action"><option value="hold">Hold for operator review</option><option value="refund_wallet">Revoke access, then refund wallet</option></select></label>
    <label class="field"><span>Automatic renewal trigger</span><select v-model="policy.renewal_trigger"><option value="expiry">Expiry</option><option value="quota">Quota exhausted</option><option value="either">Expiry or quota</option></select></label>
    <label class="field"><span>Quota at renewal</span><select v-model="policy.renewal_quota"><option value="reset">Reset to purchased quota</option><option value="carry_unused">Purchased quota plus unused previous balance</option></select></label>
    <label class="field"><span>Price Renewal</span><select v-model="policy.renewal_price"><option value="purchased">Purchase price snapshot</option><option value="current_plan">Current plan price</option></select></label>
  </div>
</template>
