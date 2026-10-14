<script setup lang="ts">
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import LoginForm from "@papilio/auth/LoginForm.vue";
const router = useRouter();
const { t } = useI18n();
</script>
<template>
  <div class="login-shell">
    <div class="login-art"><div class="login-wordmark"><img class="papilio-logo papilio-logo-dark" src="/papilio-logo-dark.png" width="636" height="256" alt="Papilio" /><img class="papilio-logo papilio-logo-light" src="/papilio-logo-light.png" width="636" height="256" alt="Papilio" /></div><h1>{{ t("resellerLogin.title") }}</h1><p>{{ t("resellerLogin.description") }}</p></div>
    <div class="login-panel"><LoginForm realm="reseller" @signed-in="router.push('/reseller')" /></div>
  </div>
</template>
