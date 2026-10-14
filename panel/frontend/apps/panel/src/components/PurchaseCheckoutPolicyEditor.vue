<script setup lang="ts">
import { ref, watch } from "vue";
import { type CheckoutTransientConflictMode, type PurchaseCheckoutPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
const props=defineProps<{modelValue:PurchaseCheckoutPolicy|null;transientModes?:CheckoutTransientConflictMode[]}>();
const emit=defineEmits<{"update:modelValue":[value:PurchaseCheckoutPolicy];valid:[value:boolean]}>();
const expiry=ref(""),enabled=ref(false),admission=ref<PurchaseCheckoutPolicy["admission_mode"]>("require_ready_bundle");
const recovery=ref<CheckoutTransientConflictMode>("retry_until_expiry");
watch(()=>props.modelValue,value=>{expiry.value=value?String(value.default_expiry_seconds):"";enabled.value=value?.enabled??false;admission.value=value?.admission_mode??"require_ready_bundle";recovery.value=value?.transient_conflict_action??"retry_until_expiry";},{immediate:true});
watch([expiry,enabled,()=>props.modelValue],()=>emit("valid",(!props.modelValue&&!enabled.value&&!expiry.value)||(Number.isSafeInteger(Number(expiry.value))&&Number(expiry.value)>0)),{immediate:true});
function apply():void{const seconds=Number(expiry.value);if(!Number.isSafeInteger(seconds)||seconds<=0)return;emit("update:modelValue",{enabled:enabled.value,admission_mode:admission.value,default_expiry_seconds:seconds,...(props.transientModes?.includes(recovery.value)?{transient_conflict_action:recovery.value}:{})});}
</script>
<template><section class="form-grid" :aria-label="t('settingsEditors.purchase.title')"><h3>{{t('settingsEditors.purchase.title')}}</h3><p>{{t('settingsEditors.purchase.description')}}</p><p v-if="!modelValue">{{t('settingsEditors.purchase.missing')}}</p><label class="check-row"><input v-model="enabled" type="checkbox" @change="apply" />{{t('settingsEditors.purchase.enable')}}</label><label class="field"><span>{{t('settingsEditors.purchase.delivery')}}</span><select v-model="admission" @change="apply"><option value="require_ready_bundle">{{t('settingsEditors.purchase.ready')}}</option><option value="allow_manual_profiles">{{t('settingsEditors.purchase.manual')}}</option></select></label><label v-if="transientModes?.length" class="field"><span>{{t('settingsEditors.purchase.busy')}}</span><select v-model="recovery" :aria-label="t('settingsEditors.purchase.transientPolicy')" @change="apply"><option v-for="mode in transientModes" :key="mode" :value="mode">{{t(`settingsEditors.purchase.${mode==='retry_until_expiry'?'retry':'confirm'}`)}}</option></select><small>{{t('settingsEditors.purchase.retryHint')}}</small></label><NumField v-model="expiry" :label="t('settingsEditors.purchase.lifetime')" @update:model-value="apply" /><button type="button" class="btn secondary" :disabled="!Number.isSafeInteger(Number(expiry))||Number(expiry)<=0" @click="apply">{{t('settingsEditors.purchase.apply')}}</button></section></template>
