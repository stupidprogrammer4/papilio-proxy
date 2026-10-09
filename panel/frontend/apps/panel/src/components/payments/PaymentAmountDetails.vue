<script setup lang="ts">
import { computed } from "vue";
import { type PaymentIdentifierMode } from "@papilio/api";
import { toman } from "@papilio/ui";
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
<template><section class="hint-box payment-amount" aria-label="Exact payment amount"><p v-if="payableValid"><strong>Exact transfer amount: <span class="tabular" dir="ltr">{{String(payableAmountRial)}} RIAL</span></strong></p><p v-else class="message error" role="alert">The exact payment amount cannot be displayed safely. Refresh the payment details before transferring.</p><template v-if="payableValid"><p v-if="requestedValid">Requested wallet top-up: <span class="tabular" dir="ltr">{{String(requestedAmountRial)}} RIAL</span></p><p v-if="adjustment!==null">Payment identifier adjustment: <span class="tabular" dir="ltr">{{adjustment>=0?'+':''}}{{String(adjustment)}} RIAL</span></p><p v-if="identifierMode==='rial_suffix4'">Payment identifier: <strong class="tabular" dir="ltr">{{code4??'Not recorded'}}</strong>. Transfer the complete RIAL amount above, including its final digits.</p><p>After approval, the full <span class="tabular" dir="ltr">{{String(payableAmountRial)}} RIAL</span> is credited to your wallet. This payment amount does not change the saved plan price.</p><small>Secondary amount: {{toman(payableAmountRial)}}. Use the exact RIAL amount for your bank transfer.</small></template></section></template>
<style scoped>.payment-amount{overflow-wrap:anywhere}.payment-amount p{margin:8px 0}</style>
