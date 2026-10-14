<script setup lang="ts">
import { computed } from "vue";
import { type PaymentIdentifierMode } from "@papilio/api";
import { useLocalizedFormats } from "../../composables/useLocalizedFormats";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
const { toman: formatToman } = useLocalizedFormats();
const props=defineProps<{payableAmountRial:number;requestedAmountRial?:number|null;identifierMode?:PaymentIdentifierMode;code4?:string|null}>();
const requestedValid=computed(()=>props.requestedAmountRial!=null&&Number.isSafeInteger(props.requestedAmountRial)&&props.requestedAmountRial>0);
const payableValid=computed(()=>{
  if(!Number.isSafeInteger(props.payableAmountRial)||props.payableAmountRial<=0)return false;
  if(props.requestedAmountRial!=null&&(!requestedValid.value||props.requestedAmountRial>props.payableAmountRial))return false;
  if(props.identifierMode==='rial_suffix4')return requestedValid.value&&typeof props.code4==='string'&&/^[0-9]{4}$/.test(props.code4)&&Number(props.code4)===props.payableAmountRial%10000;
  return (props.identifierMode===undefined||props.identifierMode==='exact_requested')&&props.code4==null;
});
const adjustment=computed(()=>payableValid.value&&requestedValid.value?props.payableAmountRial-props.requestedAmountRial!:null);
</script>
<template><section class="hint-box payment-amount" :aria-label="t('payments.amountDetails.aria')"><p v-if="payableValid"><strong>{{ t('payments.amountDetails.exact') }}: <span class="tabular" dir="ltr">{{String(payableAmountRial)}} {{ t('payments.amountDetails.rial') }}</span></strong></p><p v-else class="message error" role="alert">{{ t('payments.amountDetails.unsafe') }}</p><template v-if="payableValid"><p v-if="requestedValid">{{ t('payments.amountDetails.requested') }}: <span class="tabular" dir="ltr">{{String(requestedAmountRial)}} {{ t('payments.amountDetails.rial') }}</span></p><p v-if="adjustment!==null">{{ t('payments.amountDetails.adjustment') }}: <span class="tabular" dir="ltr">{{adjustment>=0?'+':''}}{{String(adjustment)}} {{ t('payments.amountDetails.rial') }}</span></p><p v-if="identifierMode==='rial_suffix4'">{{ t('payments.amountDetails.identifier') }}: <strong class="tabular" dir="ltr">{{code4??t('payments.amountDetails.notRecorded')}}</strong>. {{ t('payments.amountDetails.suffixHint') }}</p><p>{{ t('payments.amountDetails.walletCredit', { amount: `${String(payableAmountRial)} ${t('payments.amountDetails.rial')}` }) }}</p><small>{{ t('payments.amountDetails.secondary', { amount: formatToman(payableAmountRial) }) }}</small></template></section></template>
<style scoped>.payment-amount{overflow-wrap:anywhere}.payment-amount p{margin:8px 0}</style>
