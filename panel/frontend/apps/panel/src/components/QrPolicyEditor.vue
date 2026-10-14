<script setup lang="ts">
import { type QrPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
const props = defineProps<{ modelValue: QrPolicy }>();
const emit = defineEmits<{ "update:modelValue": [value: QrPolicy] }>();
function change<K extends keyof QrPolicy>(key: K, value: QrPolicy[K]): void { emit("update:modelValue", { ...props.modelValue, [key]: value }); }
</script>
<template>
  <fieldset class="form-grid"><legend>{{t('settingsEditors.qr.title')}}</legend>
    <label class="check-row"><input :checked="modelValue.enabled" type="checkbox" @change="change('enabled', ($event.target as HTMLInputElement).checked)" />{{t('settingsEditors.qr.enable')}}</label>
    <label class="field"><span>{{t('settingsEditors.qr.correction')}}</span><select :value="modelValue.error_correction" @change="change('error_correction', ($event.target as HTMLSelectElement).value as QrPolicy['error_correction'])"><option value="L">{{t('settingsEditors.qr.low')}}</option><option value="M">{{t('settingsEditors.qr.medium')}}</option><option value="Q">{{t('settingsEditors.qr.high')}}</option><option value="H">{{t('settingsEditors.qr.maximum')}}</option></select></label>
    <NumField :model-value="String(modelValue.box_size)" :label="t('settingsEditors.qr.size')" @update:model-value="change('box_size', Number($event))" />
    <NumField :model-value="String(modelValue.border_modules)" :label="t('settingsEditors.qr.border')" @update:model-value="change('border_modules', Number($event))" />
    <p class="hint-box">{{t('settingsEditors.qr.hint')}}</p>
  </fieldset>
</template>
