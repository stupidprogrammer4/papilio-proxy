<script setup lang="ts">
import NotificationRecords from "../components/notifications/NotificationRecords.vue";
</script>
<template><main class="customer-shell"><div class="page-head"><div><p class="eyebrow">Customer account</p><h1>My notifications</h1></div><RouterLink class="btn secondary" to="/account">Customer account</RouterLink></div><NotificationRecords audience="customer" /></main></template>
