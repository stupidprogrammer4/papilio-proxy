<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError } from "@papilio/api";
import { useAuth, useResellerAuth } from "./index";

const props = withDefaults(defineProps<{ realm?: "admin" | "reseller" }>(), { realm: "admin" });
const emit = defineEmits<{ signedIn: [] }>();
const { t, te } = useI18n();
const auth = props.realm === "reseller" ? useResellerAuth() : useAuth();
const username = ref("");
const password = ref("");
const failure = ref<unknown>(null);
const busy = ref(false);
const error = computed(() => {
  if (!failure.value) return "";
  if (failure.value instanceof ApiError) {
    const key = `errors.${failure.value.code}`;
    return te(key) ? t(key) : failure.value.message;
  }
  return t("login.failed");
});

async function submit(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  failure.value = null;
  try {
    await auth.login(username.value.trim(), password.value);
    password.value = "";
    emit("signedIn");
  } catch (cause) {
    failure.value = cause;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <form class="login-card form-grid" @submit.prevent="submit"><div><p class="eyebrow">{{t(realm==='reseller'?'login.reseller':'login.admin')}}</p><h2>{{t("login.title")}}</h2><p>{{t(realm==='reseller'?'login.resellerDescription':'login.staffDescription')}}</p></div><label class="field"><span>{{t("login.username")}}</span><input v-model="username" autocomplete="username" required dir="ltr" :disabled="busy" /></label><label class="field"><span>{{t("login.password")}}</span><input v-model="password" type="password" autocomplete="current-password" minlength="8" maxlength="256" required :disabled="busy" /></label><p v-if="error" class="message error" role="alert">{{ error }}</p><button class="btn" :disabled="busy">{{ t(busy?'login.busy':'login.submit') }}</button></form>
</template>
