<script setup lang="ts">
import { computed } from "vue";
import { asciiDigits, faDigits } from "./index";

const props = defineProps<{ modelValue: string; disabled?: boolean; min?: number; decimal?: boolean; signed?: boolean; label: string; placeholder?: string }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const displayed = computed(() => faDigits(props.modelValue));
function input(event: Event): void {
  const target = event.target as HTMLInputElement;
  const raw = asciiDigits(target.value).replace(/٫/g, ".");
  const sign = props.signed && raw.startsWith("-") ? "-" : "";
  const filtered = raw.replace(props.decimal ? /[^0-9.]/g : /[^0-9]/g, "");
  const parts = filtered.split(".");
  const value = sign + (props.decimal && parts.length > 1 ? `${parts[0] ?? ""}.${(parts[1] ?? "").slice(0, 1)}` : filtered);
  emit("update:modelValue", value);
  target.value = faDigits(value);
}
</script>

<template>
  <label class="field">
    <span>{{ label }}</span>
    <input :disabled="disabled" :value="displayed" inputmode="numeric" :placeholder="placeholder" @input="input" />
  </label>
</template>
