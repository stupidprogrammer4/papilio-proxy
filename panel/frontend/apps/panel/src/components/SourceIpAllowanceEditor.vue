<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { IpLimitCapacityRead, IpLimitChoice } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import { faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";

const props = defineProps<{ modelValue: IpLimitChoice | null; defaults: IpLimitChoice | null; capacity: IpLimitCapacityRead | null; allowLegacy?: boolean }>();
const { t } = useI18n();
const emit = defineEmits<{ "update:modelValue": [value: IpLimitChoice | null]; validity: [valid: boolean] }>();
type AllowanceSelection = "" | "one" | "custom" | "unlimited" | "legacy";
const selection = ref<AllowanceSelection>("");
const numbers = ref({ max_ips: "", lease_seconds: "", ban_seconds: "" });
watch(() => props.modelValue, policy => {
  if (!policy) return;
  for (const key of ["max_ips", "lease_seconds", "ban_seconds"] as const) {
    if (numbers.value[key] === "" && policy[key] === 0) continue;
    if (Number(numbers.value[key]) !== policy[key] || numbers.value[key] === "") numbers.value[key] = String(policy[key]);
  }
}, { immediate: true });
function restore(): void {
  if (props.modelValue === null) selection.value = props.allowLegacy ? "legacy" : "";
  else selection.value = !props.modelValue.enabled ? "unlimited" : props.modelValue.max_ips === 1 ? "one" : "custom";
}
function choose(value: AllowanceSelection): void {
  selection.value = value;
  if (value === "legacy") { emit("update:modelValue", null); return; }
  const base = props.modelValue ?? props.defaults;
  if (!base || !value) return;
  emit("update:modelValue", { ...base, enabled: value !== "unlimited", max_ips: value === "one" ? 1 : base.max_ips });
}
function number(key: "max_ips" | "lease_seconds" | "ban_seconds", value: string): void {
  numbers.value[key] = value;
  if (props.modelValue) emit("update:modelValue", { ...props.modelValue, [key]: Number(value) });
}
const valid = computed(() => {
  if (selection.value === "legacy") return props.allowLegacy === true;
  const policy = props.modelValue, cap = props.capacity;
  if (!selection.value || !policy || !cap) return false;
  return [policy.max_ips, policy.lease_seconds, policy.ban_seconds, cap.max_ips_ceiling, cap.max_lease_seconds, cap.max_ban_seconds].every(value => Number.isSafeInteger(value) && value > 0)
    && policy.max_ips <= cap.max_ips_ceiling && policy.lease_seconds <= cap.max_lease_seconds && policy.ban_seconds <= cap.max_ban_seconds;
});
function allowanceText(policy: IpLimitChoice | null): string {
  if (!policy) return t("plans.ip.noRestriction");
  if (!policy.enabled) return t("plans.ip.unlimited");
  if (!Number.isSafeInteger(policy.max_ips) || policy.max_ips <= 0) return t("plans.ip.invalid");
  if (policy.max_ips === 1) return t("plans.ip.one");
  return t("plans.ip.upTo", { count: policy.max_ips });
}
watch(valid, value => emit("validity", value), { immediate: true });
watch(() => props.modelValue, (value, old) => { if (value !== null && old === null && selection.value) return; if (!selection.value || value === null) restore(); });
restore();
</script>

<template>
  <section class="form-grid" :aria-label="t('plans.ip.aria')">
    <h3>{{ t("plans.ip.heading") }}</h3>
    <label class="field"><span>{{ t("plans.ip.allowance") }}</span><select :value="selection" :aria-label="t('plans.ip.allowance')" :disabled="!defaults && !modelValue" @change="choose(($event.target as HTMLSelectElement).value as AllowanceSelection)"><option value="" disabled>{{ t("plans.ip.choose") }}</option><option value="one">{{ t("plans.ip.one") }}</option><option value="custom">{{ t("plans.ip.custom") }}</option><option value="unlimited">{{ t("plans.ip.unlimited") }}</option><option v-if="allowLegacy" value="legacy">{{ t("plans.ip.legacy") }}</option></select></label>
    <p v-if="selection==='legacy'" class="message">{{ t("plans.ip.legacyPolicy", { allowance: allowanceText(defaults) }) }}</p>
    <p v-if="!capacity && selection!=='legacy'" class="message error" role="alert">{{ t("plans.ip.capacityUnavailable") }}</p>
    <template v-if="modelValue && selection!=='' && selection!=='legacy'">
      <NumField v-if="selection==='custom'" :model-value="numbers.max_ips" :label="t('plans.ip.maximum')" @update:model-value="number('max_ips',$event)" />
      <p v-if="capacity && selection!=='unlimited'" class="subtitle">{{ t("plans.ip.configuredMaximum", { count: faNumber(capacity.max_ips_ceiling) }) }}</p>
      <details><summary>{{ t("plans.ip.advanced") }}</summary><div class="form-grid"><NumField :model-value="numbers.lease_seconds" :label="t('plans.ip.activityWindow')" @update:model-value="number('lease_seconds',$event)" /><NumField :model-value="numbers.ban_seconds" :label="t('plans.ip.banDuration')" @update:model-value="number('ban_seconds',$event)" /><label class="field"><span>{{ t("plans.ip.atLimit") }}</span><select :value="modelValue.mode" :aria-label="t('plans.ip.atLimit')" @change="emit('update:modelValue',{...modelValue,mode:($event.target as HTMLSelectElement).value as IpLimitChoice['mode']})"><option value="reject_new">{{ t("plans.ip.rejectNew") }}</option><option value="replace_oldest">{{ t("plans.ip.replaceOldest") }}</option></select></label><p v-if="capacity" class="subtitle">{{ t("plans.ip.capacityLimits", { lease: faNumber(capacity.max_lease_seconds), ban: faNumber(capacity.max_ban_seconds) }) }}</p></div></details>
    </template>
    <p class="subtitle">{{ t("plans.ip.shared") }}</p>
  </section>
</template>
