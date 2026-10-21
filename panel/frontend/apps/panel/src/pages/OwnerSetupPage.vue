<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { request, setCsrf } from "@papilio/api";

const { t } = useI18n();
const router = useRouter();
const token = ref("");
const username = ref("");
const password = ref("");
const busy = ref(false);
const error = ref("");

async function submit(): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    const csrf = await request<{ csrf_token: string }>("/v1/admin/auth/csrf");
    setCsrf(csrf.csrf_token);
    await request("/v1/setup/owner", "POST", {
      token: token.value.trim(), username: username.value.trim(), password: password.value,
    });
    token.value = "";
    password.value = "";
    await router.push("/login");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("login.failed");
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="login-shell">
    <section class="login-panel">
      <form class="login-card form-grid" @submit.prevent="submit">
        <h1>{{ t("foundation.setupTitle") }}</h1>
        <p>{{ t("foundation.setupHelp") }}</p>
        <label class="field"><span>{{ t("foundation.token") }}</span><input v-model="token" data-testid="setup-token" type="password" autocomplete="off" required :disabled="busy" /></label>
        <label class="field"><span>{{ t("foundation.username") }}</span><input v-model="username" data-testid="setup-username" autocomplete="username" maxlength="150" required :disabled="busy" /></label>
        <label class="field"><span>{{ t("foundation.password") }}</span><input v-model="password" data-testid="setup-password" type="password" autocomplete="new-password" maxlength="1024" required :disabled="busy" /></label>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <button class="btn" data-testid="setup-submit" type="submit" :disabled="busy">{{ t(busy ? "foundation.working" : "foundation.createOwner") }}</button>
        <RouterLink to="/login">{{ t("foundation.login") }}</RouterLink>
      </form>
    </section>
  </main>
</template>
