<script setup lang="ts">
import { useRouter } from "vue-router";
import LoginForm from "@papilio/auth/LoginForm.vue";
const router = useRouter();
</script>
<template>
  <div class="login-shell">
    <div class="login-art"><div class="brand-mark">✦</div><h1>Your reseller workspace.</h1><p>Manage customers, plan agreements, wallets and your reseller team.</p></div>
    <div class="login-panel"><LoginForm realm="reseller" @signed-in="router.push('/reseller')" /></div>
  </div>
</template>
