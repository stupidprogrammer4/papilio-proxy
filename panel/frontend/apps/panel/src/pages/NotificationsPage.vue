<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { computed } from "vue";
import { useRoute } from "vue-router";
import NotificationRecords from "../components/notifications/NotificationRecords.vue";
const { t } = useI18n();
const route=useRoute();
const customerId=computed(()=>{const value=route.query.customer_id;if(typeof value!=="string"||!/^\d+$/.test(value))return undefined;const id=Number(value);return Number.isSafeInteger(id)&&id>0?id:undefined;});
</script>
<template><div class="page-head"><div><p class="eyebrow">{{ t('notifications.eyebrow') }}</p><h1>{{ t('notifications.title') }}</h1><p class="subtitle">{{ t('notifications.description') }}</p></div></div><NotificationRecords audience="admin" :customer-id="customerId" /></template>
