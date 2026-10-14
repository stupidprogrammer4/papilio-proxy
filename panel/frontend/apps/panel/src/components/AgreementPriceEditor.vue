<script setup lang="ts">
import type { AgreementPrice } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
const price=defineModel<AgreementPrice>({required:true});
defineProps<{disabled?:boolean}>();
function number(key:"fixed_price_rial"|"discount_bps"|"quantum_rial",value:string):void{price.value={...price.value,[key]:value===""&&key!=="quantum_rial"?null:Number(value)};}
function mode(event:Event):void{price.value={...price.value,mode:(event.target as HTMLSelectElement).value as AgreementPrice["mode"],fixed_price_rial:null,discount_bps:null};}
</script>
<template><fieldset class="form-grid" :disabled="disabled"><legend>{{ t('agreementPrice.title') }}</legend><label class="field"><span>{{ t('agreementPrice.method') }}</span><select :aria-label="t('agreementPrice.method')" :value="price.mode" @change="mode"><option value="catalog">{{ t('agreementPrice.catalog') }}</option><option value="fixed">{{ t('agreementPrice.fixed') }}</option><option value="discount">{{ t('agreementPrice.discount') }}</option></select></label><NumField v-if="price.mode==='fixed'" :model-value="price.fixed_price_rial===null?'':String(price.fixed_price_rial)" :label="t('agreementPrice.fixedAmount')" @update:model-value="number('fixed_price_rial',$event)"/><NumField v-if="price.mode==='discount'" :model-value="price.discount_bps===null?'':String(price.discount_bps)" :label="t('agreementPrice.discountBps')" @update:model-value="number('discount_bps',$event)"/><label class="field"><span>{{ t('agreementPrice.rounding') }}</span><select :aria-label="t('agreementPrice.rounding')" v-model="price.rounding"><option value="floor">{{ t('agreementPrice.floor') }}</option><option value="ceil">{{ t('agreementPrice.ceil') }}</option><option value="nearest">{{ t('agreementPrice.nearest') }}</option></select></label><NumField :model-value="String(price.quantum_rial)" :label="t('agreementPrice.increment')" @update:model-value="number('quantum_rial',$event)"/></fieldset></template>
<style scoped>fieldset{border:1px solid var(--line);border-radius:12px;padding:16px}</style>
