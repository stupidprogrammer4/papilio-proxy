<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import LoginForm from "@papilio/auth/LoginForm.vue";
import Icon from "@papilio/ui/Icon.vue";
const router=useRouter();
const { t } = useI18n();
</script>
<template>
  <div class="login-shell">
    <section class="login-art">
      <div class="login-wordmark"><img class="papilio-logo papilio-logo-dark" src="/papilio-logo-dark.png" width="636" height="256" alt="Papilio" /><img class="papilio-logo papilio-logo-light" src="/papilio-logo-light.png" width="636" height="256" alt="Papilio" /></div>
      <div class="login-story"><p class="eyebrow">{{t('login.workspace')}}</p><h1>{{t("login.hero")}}</h1><p>{{t("login.description")}}</p></div>
      <div class="login-capabilities"><span><Icon name="layers" />{{t('login.configuration')}}</span><span><Icon name="wallet" />{{t('login.commerce')}}</span><span><Icon name="bolt" />{{t('login.automation')}}</span></div>
    </section>
    <section class="login-panel">
      <div class="login-panel-content"><div class="login-mobile-brand"><img class="papilio-logo papilio-logo-dark" src="/papilio-logo-dark.png" width="636" height="256" alt="Papilio" /><img class="papilio-logo papilio-logo-light" src="/papilio-logo-light.png" width="636" height="256" alt="Papilio" /></div><LoginForm @signed-in="router.push('/')" /></div>
    </section>
  </div>
</template>
