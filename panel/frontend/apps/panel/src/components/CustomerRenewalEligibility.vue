<script setup lang="ts">
import {ref,watch,onUnmounted} from 'vue';
import {item,type CustomerRenewalEligibility} from '@papilio/api';
import { useI18n } from 'vue-i18n';
import { useLocalizedFormats } from '../composables/useLocalizedFormats';
const props=defineProps<{subscriptionId:number;refreshKey?:boolean}>();
const { t } = useI18n();
const { date, toman } = useLocalizedFormats();
const value=ref<CustomerRenewalEligibility|null>(null);const busy=ref(false);const error=ref('');let sequence=0;
const reasonKeys:Record<string,string>={trial_not_renewable:'trialNotRenewable',subscription_not_renewable:'subscriptionNotRenewable',customer_renewals_disabled:'customerDisabled',payer_renewals_disabled:'payerDisabled',renewal_quote_unavailable:'quoteUnavailable'};
async function load():Promise<void>{const stamp=++sequence;busy.value=true;value.value=null;error.value='';try{const result=await item<CustomerRenewalEligibility>(`/v1/customer/subscriptions/${props.subscriptionId}/renewal-eligibility`);if(stamp===sequence)value.value=result;}catch(cause){if(stamp===sequence)error.value=cause instanceof Error?cause.message:t("customerRenewal.loadFailed");}finally{if(stamp===sequence)busy.value=false;}}
watch(()=>[props.subscriptionId,props.refreshKey],()=>{void load();},{immediate:true});onUnmounted(()=>{sequence++;});
</script>
<template><section class="hint-box stack" :aria-label="t('customerRenewal.region')"><h4>{{ t("customerRenewal.title") }}</h4><p v-if="busy">{{ t("customerRenewal.checking") }}</p><p v-if="error" class="message error" role="alert">{{error}}</p><template v-if="value"><p>{{ t("customerRenewal.checked") }}: {{date(value.checked_at)}}</p><p>{{value.eligible?t('customerRenewal.eligible'):t(`customerRenewal.reasons.${reasonKeys[value.reason_code??'']??'unavailable'}`)}}</p><p>{{ t("customerRenewal.price") }}: {{value.renewal_price_rial===null?t("customerRenewal.unavailable"):toman(value.renewal_price_rial)}}</p><template v-if="value.payer_kind==='self'"><p>{{ t("customerRenewal.wallet") }}: {{value.wallet_balance_rial===null?t("customerRenewal.unavailable"):toman(value.wallet_balance_rial)}}</p><p v-if="value.wallet_shortfall_rial!==null">{{ t("customerRenewal.shortfall") }}: {{toman(value.wallet_shortfall_rial)}}</p></template><p v-else>{{ t("customerRenewal.otherPayer") }}</p><p>{{value.renewal_due?t('customerRenewal.triggerReached'):t('customerRenewal.triggerPending')}}</p><p>{{value.auto_renew_authorized?t('customerRenewal.authorized'):t('customerRenewal.notAuthorized')}} {{ t('customerRenewal.executionNote') }}</p></template><button class="btn secondary" type="button" :disabled="busy" @click="load">{{ t("customerRenewal.refresh") }}</button></section></template>
