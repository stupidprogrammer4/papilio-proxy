<script setup lang="ts">
import { useI18n } from "vue-i18n";
import NotificationRecords from "../components/notifications/NotificationRecords.vue";
const {t}=useI18n();
</script>
<template><main class="customer-shell"><div class="page-head"><div><p class="eyebrow">{{t("customerSignIn.eyebrow")}}</p><h1>{{t("customerSignIn.notifications")}}</h1></div><RouterLink class="btn secondary" to="/account">{{t("customerSignIn.account")}}</RouterLink></div><NotificationRecords audience="customer" /></main></template>
