<script setup lang="ts">
import type { QuotaPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
const policy = defineModel<QuotaPolicy>({ required: true });
const fields = [
  { key: "grant_bytes", label: "plans.quotaPolicy.grantBytes" },
  { key: "grant_seconds", label: "plans.quotaPolicy.grantSeconds" },
  { key: "report_max_age_seconds", label: "plans.quotaPolicy.reportAge" },
  { key: "report_future_seconds", label: "plans.quotaPolicy.futureSkew" },
] as const;
function number(key: typeof fields[number]["key"], value: string): void { policy.value = { ...policy.value, [key]: Number(value) }; }
</script>
<template>
  <div class="form-grid">
    <label class="field"><span>{{ t("plans.quotaPolicy.mode") }}</span><select v-model="policy.mode"><option value="reported">{{ t("plans.quotaPolicy.reported") }}</option><option value="reserved">{{ t("plans.quotaPolicy.reserved") }}</option></select></label>
    <p class="hint-box">{{ t("plans.quotaPolicy.explanation") }}</p>
    <NumField v-for="field in fields" :key="field.key" :model-value="String(policy[field.key])" :label="t(field.label)" @update:model-value="number(field.key, $event)" />
  </div>
</template>
