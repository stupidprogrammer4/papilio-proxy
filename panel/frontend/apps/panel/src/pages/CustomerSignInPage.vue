<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useCustomerAuth } from "@papilio/auth";
const auth=useCustomerAuth(); const router=useRouter();const route=useRoute();const {t}=useI18n(); const token=ref(window.location.hash.slice(1)); const busy=ref(false); const error=ref("");
async function enter():Promise<void> { busy.value=true;error.value="";try { if(token.value) { await auth.exchange(token.value);token.value=""; } else { await auth.restore();if(!auth.session)throw new Error(auth.error || t("customerSignIn.botLinkRequired")); } await router.replace(route.query.section==="support"?"/account/support":"/account"); } catch(cause) {error.value=cause instanceof Error?cause.message:t("customerSignIn.failed");} finally {busy.value=false;} }
onMounted(()=>{ if(token.value) { window.history.replaceState(null,"",window.location.pathname+window.location.search);void enter(); } });
</script>
<template><main class="customer-shell"><section class="card card-pad form-grid"><p class="eyebrow">{{ t("customerSignIn.eyebrow") }}</p><h1>{{ t("customerSignIn.title") }}</h1><p>{{ t("customerSignIn.description") }}</p><p>{{ t("customerSignIn.subscriptionHint") }}</p><p v-if="error" class="message error" role="alert">{{ error }}</p><button class="btn" :disabled="busy" @click="enter">{{ busy ? t("customerSignIn.busy") : token ? t("customerSignIn.retry") : t("customerSignIn.check") }}</button></section></main></template>
