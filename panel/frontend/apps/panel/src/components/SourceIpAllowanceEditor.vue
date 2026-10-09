<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { IpLimitCapacityRead, IpLimitChoice } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import { ipAllowanceText } from "./ipLimits/policy";

const props = defineProps<{ modelValue: IpLimitChoice | null; defaults: IpLimitChoice | null; capacity: IpLimitCapacityRead | null; allowLegacy?: boolean }>();
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
watch(valid, value => emit("validity", value), { immediate: true });
watch(() => props.modelValue, (value, old) => { if (value !== null && old === null && selection.value) return; if (!selection.value || value === null) restore(); });
restore();
</script>

<template>
  <section class="form-grid" aria-label="Plan source IP concurrency">
    <h3>Source IP concurrency</h3>
    <label class="field"><span>Concurrent source IP allowance</span><select :value="selection" aria-label="Concurrent source IP allowance" :disabled="!defaults && !modelValue" @change="choose(($event.target as HTMLSelectElement).value as AllowanceSelection)"><option value="" disabled>Choose an allowance</option><option value="one">1 source IP</option><option value="custom">Custom number of source IPs</option><option value="unlimited">Unlimited source IPs</option><option v-if="allowLegacy" value="legacy">Keep legacy purchase-time defaults</option></select></label>
    <p v-if="selection==='legacy'" class="message">This legacy plan uses the defaults in effect when a purchase is made. Current allowance: {{ipAllowanceText(defaults)}}. Choose 1, a custom number or unlimited to save explicit terms for future purchases.</p>
    <p v-if="!capacity && selection!=='legacy'" class="message error" role="alert">The API has not supplied source-IP capacities. Reload plan defaults before saving.</p>
    <template v-if="modelValue && selection!=='' && selection!=='legacy'">
      <NumField v-if="selection==='custom'" :model-value="numbers.max_ips" label="Maximum concurrent source IPs" @update:model-value="number('max_ips',$event)" />
      <p v-if="capacity && selection!=='unlimited'" class="subtitle">Configured maximum: {{capacity.max_ips_ceiling}} source IPs.</p>
      <details><summary>Advanced admission policy</summary><div class="form-grid"><NumField :model-value="numbers.lease_seconds" label="IP activity window (seconds)" @update:model-value="number('lease_seconds',$event)" /><NumField :model-value="numbers.ban_seconds" label="Extra IP ban duration (seconds)" @update:model-value="number('ban_seconds',$event)" /><label class="field"><span>Behavior at the limit</span><select :value="modelValue.mode" aria-label="Behavior at the limit" @change="emit('update:modelValue',{...modelValue,mode:($event.target as HTMLSelectElement).value as IpLimitChoice['mode']})"><option value="reject_new">Reject the new source IP</option><option value="replace_oldest">Replace the oldest source IP</option></select></label><p v-if="capacity" class="subtitle">Maximum activity window {{capacity.max_lease_seconds}} seconds · Maximum ban {{capacity.max_ban_seconds}} seconds.</p></div></details>
    </template>
    <p class="subtitle">One allowance is shared across a subscription's configurations. Source IP counts do not represent device counts. Core enforcement is not verified.</p>
  </section>
</template>
