<script setup lang="ts">
import type { IpLimitChoice } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
const policy = defineModel<IpLimitChoice>({ required: true });
const fields = [{ key: "max_ips", label: "Active IP limit" }, { key: "lease_seconds", label: "IP lease duration (seconds)" }, { key: "ban_seconds", label: "Extra IP ban duration (seconds)" }] as const;
function number(key: typeof fields[number]["key"], value: string): void { policy.value = { ...policy.value, [key]: Number(value) }; }
</script>
<template>
  <div class="form-grid"><label class="check-row"><input v-model="policy.enabled" type="checkbox" />Enable IP limits</label><NumField v-for="field in fields" :key="field.key" :model-value="String(policy[field.key])" :label="field.label" @update:model-value="number(field.key, $event)" /><label class="field"><span>Extra IP behavior</span><select v-model="policy.mode"><option value="reject_new">Reject new IP</option><option value="replace_oldest">Replace oldest IP</option></select></label></div>
</template>
