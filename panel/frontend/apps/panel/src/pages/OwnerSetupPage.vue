<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { request, setCsrf, type LocalNodeDefaults } from "@papilio/api";
import LocalNodeDefinition from "../components/LocalNodeDefinition.vue";

const { t } = useI18n();
const router = useRouter();
const token = ref("");
const username = ref("");
const password = ref("");
const busy = ref(false);
const error = ref("");
const defaults = ref<LocalNodeDefaults | null>(null);
const localEnabled = ref(false);
const lifetime = new AbortController();
onBeforeUnmount(() => lifetime.abort());

async function loadDefaults(): Promise<void> {
  busy.value = true; error.value = "";
  try {
    const result = await request<LocalNodeDefaults>("/v1/setup/local-node", "GET", undefined, { signal: lifetime.signal });
    if (!defaults.value) { defaults.value = result; localEnabled.value = result.available; }
  } catch (cause) {
    if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("login.failed");
  } finally { busy.value = false; }
}

async function submit(): Promise<void> {
  if (!defaults.value || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const csrf = await request<{ csrf_token: string }>("/v1/admin/auth/csrf");
    setCsrf(csrf.csrf_token);
    await request("/v1/setup/owner", "POST", {
      token: token.value.trim(), username: username.value.trim(), password: password.value,
      local_node: localEnabled.value ? { enabled: true, definition: defaults.value.definition, delivery: defaults.value.delivery } : { enabled: false },
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
onMounted(loadDefaults);
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
        <fieldset v-if="defaults?.available" class="form-grid" :disabled="busy">
          <label class="check-field"><input v-model="localEnabled" data-testid="setup-local-enabled" type="checkbox" />{{ t('localNode.setupEnabled') }}</label>
          <p>{{ t('localNode.setupHelp') }}</p>
          <template v-if="localEnabled">
            <LocalNodeDefinition v-model="defaults.definition" />
            <details><summary>{{ t('localNode.deliverySettings') }}</summary><div class="form-grid">
              <label class="check-field"><input v-model="defaults.delivery.enabled" type="checkbox" />{{ t('localNode.deliveryEnabled') }}</label>
              <label class="field"><span>{{ t('localNode.retryInterval') }}</span><input v-model.number="defaults.delivery.retry_interval_seconds" type="number" min="1" max="2147483647" step="1" required /></label>
              <label class="field"><span>{{ t('localNode.maxAttempts') }}</span><input v-model.number="defaults.delivery.max_attempts" type="number" min="1" max="2147483647" step="1" required /></label>
            </div></details>
          </template>
        </fieldset>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <button v-if="!defaults" class="btn secondary" type="button" :disabled="busy" @click="loadDefaults">{{ t('foundation.refresh') }}</button>
        <button class="btn" data-testid="setup-submit" type="submit" :disabled="busy || !defaults">{{ t(busy ? "foundation.working" : "foundation.createOwner") }}</button>
        <RouterLink to="/login">{{ t("foundation.login") }}</RouterLink>
      </form>
    </section>
  </main>
</template>
