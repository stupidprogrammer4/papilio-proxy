<script setup lang="ts">
import type { IpLimitChoice } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
const policy = defineModel<IpLimitChoice>({ required: true });
const fields = [{ key: "max_ips", label: "maxIps" }, { key: "lease_seconds", label: "leaseSeconds" }, { key: "ban_seconds", label: "banSeconds" }] as const;
function number(key: typeof fields[number]["key"], value: string): void { policy.value = { ...policy.value, [key]: Number(value) }; }
</script>
<template>
  <div class="form-grid"><label class="check-row"><input v-model="policy.enabled" type="checkbox" />{{ t('planIpLimit.enabled') }}</label><NumField v-for="field in fields" :key="field.key" :model-value="String(policy[field.key])" :label="t('planIpLimit.' + field.label)" @update:model-value="number(field.key, $event)" /><label class="field"><span>{{ t('planIpLimit.behavior') }}</span><select v-model="policy.mode"><option value="reject_new">{{ t('planIpLimit.reject') }}</option><option value="replace_oldest">{{ t('planIpLimit.replace') }}</option></select></label></div>
</template>
