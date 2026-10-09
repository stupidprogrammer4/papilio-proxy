<script setup lang="ts">
import type { QuotaPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
const policy = defineModel<QuotaPolicy>({ required: true });
const fields = [
  { key: "grant_bytes", label: "Maximum bytes per node grant" },
  { key: "grant_seconds", label: "Validity Permission Usage (seconds)" },
  { key: "report_max_age_seconds", label: "Maximum usage report age (seconds)" },
  { key: "report_future_seconds", label: "Allowed future clock skew (seconds)" },
] as const;
function number(key: typeof fields[number]["key"], value: string): void { policy.value = { ...policy.value, [key]: Number(value) }; }
</script>
<template>
  <div class="form-grid">
    <label class="field"><span>Quota enforcement mode</span><select v-model="policy.mode"><option value="reported">Reported usage</option><option value="reserved">Shared quota reservations across nodes</option></select></label>
    <p class="hint-box">Reported usage can exceed quota when reports are delayed. Reservation mode requires each node to enforce its grant size and expiry. A disconnected node's reservation remains allocated until its final report.</p>
    <NumField v-for="field in fields" :key="field.key" :model-value="String(policy[field.key])" :label="field.label" @update:model-value="number(field.key, $event)" />
  </div>
</template>
