<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import SupportThreads from "../components/support/SupportThreads.vue";
import { useI18n } from "vue-i18n";
const route=useRoute();
const { t } = useI18n();
function record(value:unknown):number|undefined{if(typeof value!=="string"||!/^\d+$/.test(value))return undefined;const id=Number(value);return Number.isSafeInteger(id)&&id>0?id:undefined;}
const ticketId=computed(()=>record(route.query.ticket_id));const customerId=computed(()=>record(route.query.customer_id));const subscriptionId=computed(()=>record(route.query.subscription_id));const topupId=computed(()=>record(route.query.topup_id));
</script>
<template><div class="page-head"><div><p class="eyebrow">{{ t('support.eyebrow') }}</p><h1>{{ t('support.title') }}</h1><p class="subtitle">{{ t('support.description') }}</p></div></div><SupportThreads audience="admin" :ticket-id="ticketId" :customer-id="customerId" :subscription-id="subscriptionId" :topup-id="topupId" /></template>
