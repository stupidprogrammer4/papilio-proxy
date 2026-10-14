<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { type CheckoutPolicy, type PaymentIdentifierCapabilities } from "@papilio/api";
import PaymentIdentifierPolicyEditor from "./payments/PaymentIdentifierPolicyEditor.vue";
import NumField from "@papilio/ui/NumField.vue";
const props = defineProps<{ modelValue: CheckoutPolicy; identifierCapabilities?:PaymentIdentifierCapabilities }>(); const emit = defineEmits<{ "update:modelValue": [value: CheckoutPolicy]; valid:[value:boolean] }>();
const { t } = useI18n();
function change<K extends keyof CheckoutPolicy>(key: K, value: CheckoutPolicy[K]): void { emit("update:modelValue", { ...props.modelValue, [key]: value }); }
const minimum = computed({ get: () => String(props.modelValue.minimum_topup_rial / 10), set: value => change("minimum_topup_rial", Math.round(Number(value) * 10)) });
const maximum = computed({ get: () => String(props.modelValue.maximum_topup_rial / 10), set: value => change("maximum_topup_rial", Math.round(Number(value) * 10)) });
const methods = computed<{ value: CheckoutPolicy["allowed_methods"][number]; label: string }[]>(() => [{ value:"card",label:t("settingsEditors.checkout.card") },{ value:"iban",label:t("settingsEditors.checkout.iban") },{ value:"bank_account",label:t("settingsEditors.checkout.account") }]);
function toggle(value: CheckoutPolicy["allowed_methods"][number], checked: boolean): void { change("allowed_methods", checked ? [...props.modelValue.allowed_methods,value] : props.modelValue.allowed_methods.filter(row => row !== value)); }
</script>
<template><div class="form-grid"><label class="field"><span>{{t('settingsEditors.checkout.destination')}}</span><select :value="modelValue.destination_mode" @change="change('destination_mode', ($event.target as HTMLSelectElement).value as CheckoutPolicy['destination_mode'])"><option value="required">{{t('settingsEditors.checkout.required')}}</option><option value="optional">{{t('settingsEditors.checkout.optional')}}</option><option value="legacy">{{t('settingsEditors.checkout.legacy')}}</option></select></label><NumField v-model="minimum" :label="t('settingsEditors.checkout.minimum')" /><NumField v-model="maximum" :label="t('settingsEditors.checkout.maximum')" /><div><label v-for="method in methods" :key="method.value" class="check-row"><input type="checkbox" :checked="modelValue.allowed_methods.includes(method.value)" @change="toggle(method.value, ($event.target as HTMLInputElement).checked)" />{{ method.label }}</label></div><PaymentIdentifierPolicyEditor v-if="identifierCapabilities" :model-value="modelValue.payment_identifier??null" :capabilities="identifierCapabilities" @update:model-value="change('payment_identifier',$event)" @valid="emit('valid',$event)"/><p v-else class="hint-box" role="status">{{t('settingsEditors.checkout.unavailable')}}</p></div></template>
