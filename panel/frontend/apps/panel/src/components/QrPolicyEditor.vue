<script setup lang="ts">
import { type QrPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
const props = defineProps<{ modelValue: QrPolicy }>();
const emit = defineEmits<{ "update:modelValue": [value: QrPolicy] }>();
function change<K extends keyof QrPolicy>(key: K, value: QrPolicy[K]): void { emit("update:modelValue", { ...props.modelValue, [key]: value }); }
</script>
<template>
  <fieldset class="form-grid"><legend>Connection QR code</legend>
    <label class="check-row"><input :checked="modelValue.enabled" type="checkbox" @change="change('enabled', ($event.target as HTMLInputElement).checked)" />Enable connection QR codes</label>
    <label class="field"><span>Error correction</span><select :value="modelValue.error_correction" @change="change('error_correction', ($event.target as HTMLSelectElement).value as QrPolicy['error_correction'])"><option value="L">Low</option><option value="M">Medium</option><option value="Q">High</option><option value="H">Maximum</option></select></label>
    <NumField :model-value="String(modelValue.box_size)" label="Module size (pixels)" @update:model-value="change('box_size', Number($event))" />
    <NumField :model-value="String(modelValue.border_modules)" label="White border (modules)" @update:model-value="change('border_modules', Number($event))" />
    <p class="hint-box">QR codes contain private connection details. Use the link or file if the connection cannot fit in a QR code.</p>
  </fieldset>
</template>
