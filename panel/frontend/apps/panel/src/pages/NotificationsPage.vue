<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import NotificationRecords from "../components/notifications/NotificationRecords.vue";
const route=useRoute();
const customerId=computed(()=>{const value=route.query.customer_id;if(typeof value!=="string"||!/^\d+$/.test(value))return undefined;const id=Number(value);return Number.isSafeInteger(id)&&id>0?id:undefined;});
</script>
<template><div class="page-head"><div><p class="eyebrow">CUSTOMER MESSAGING</p><h1>Notifications</h1><p class="subtitle">Review delivery results, attempts and recovery decisions for each message.</p></div></div><NotificationRecords audience="admin" :customer-id="customerId" /></template>
