<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import SupportThreads from "../components/support/SupportThreads.vue";
const route=useRoute();
function record(value:unknown):number|undefined{if(typeof value!=="string"||!/^\d+$/.test(value))return undefined;const id=Number(value);return Number.isSafeInteger(id)&&id>0?id:undefined;}
const subscriptionId=computed(()=>record(route.query.subscription_id));const topupId=computed(()=>record(route.query.topup_id));
const ticketId=computed(()=>record(route.query.ticket_id));
</script>
<template><main class="customer-shell"><div class="page-head"><div><p class="eyebrow">PRIVATE SUPPORT</p><h1>Account support</h1><p class="subtitle">Only tickets belonging to your account are shown.</p></div><RouterLink class="btn secondary" to="/account">Back to account</RouterLink></div><SupportThreads audience="customer" :ticket-id="ticketId" :subscription-id="subscriptionId" :topup-id="topupId" /></main></template>
