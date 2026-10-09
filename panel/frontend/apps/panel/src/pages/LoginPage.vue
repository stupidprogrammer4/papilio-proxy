<script setup lang="ts">
import { useRouter } from "vue-router";
import LoginForm from "@papilio/auth/LoginForm.vue";
const router=useRouter();
</script>
<template>
  <div class="login-shell">
    <div class="login-art"><div class="brand-mark">✦</div><h1>Your entire service.</h1><p>Manage customers, plans, payments and delivery from a private workspace built around your business.</p></div>
    <div class="login-panel"><LoginForm @signed-in="router.push('/')" /></div>
  </div>
</template>
