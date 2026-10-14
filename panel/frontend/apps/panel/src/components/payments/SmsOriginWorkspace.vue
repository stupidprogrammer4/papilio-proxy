<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useAuth } from "@papilio/auth";
import { ApiError, item, type SmsOriginCapabilities } from "@papilio/api";
import { useI18n } from "vue-i18n";
import SmsParserProfiles from "./SmsParserProfiles.vue";
import ReceivingRealms from "./ReceivingRealms.vue";
const {t}=useI18n();
const emit=defineEmits<{capabilities:[value:SmsOriginCapabilities|null]}>();
const auth = useAuth();
const capabilities = ref<SmsOriginCapabilities|null>(null);
const state = ref<"loading"|"ready"|"unavailable"|"error">("loading");
const error = ref("");
let alive = true, sequence = 0;
async function load():Promise<void> {
  if (!auth.can("payments")) { state.value="unavailable"; return; }
  const current = ++sequence;
  state.value="loading"; error.value="";
  try {
    const result = await item<SmsOriginCapabilities>("/v1/admin/payments/sms-origins/capabilities");
    if (!alive || current!==sequence) return;
    capabilities.value=result;
    emit("capabilities",result);
    state.value=result.supported ? "ready" : "unavailable";
  } catch (cause) {
    if (!alive || current!==sequence) return;
    capabilities.value=null;
    emit("capabilities",null);
    if (cause instanceof ApiError && cause.status===404) state.value="unavailable";
    else { state.value="error"; error.value=cause instanceof Error?cause.message:t("errors.request_failed"); }
  }
}
onMounted(load);
onUnmounted(()=>{alive=false;++sequence;});
</script>
<template>
  <section class="card card-pad" :aria-label="t('paymentConfig.origin.title')">
    <div class="page-head"><div><p class="eyebrow">{{t('paymentConfig.origin.eyebrow')}}</p><h2>{{t('paymentConfig.origin.title')}}</h2><p class="subtitle">{{t('paymentConfig.origin.description')}}</p></div><button class="btn secondary" :disabled="state==='loading'" @click="load">{{t('paymentConfig.origin.refresh')}}</button></div>
    <p v-if="state==='loading'" role="status">{{t('paymentConfig.origin.loading')}}</p>
    <p v-else-if="state==='unavailable'" class="hint-box">{{t('paymentConfig.origin.unavailable')}}</p>
    <p v-else-if="state==='error'" class="message error" role="alert">{{error}}</p>
    <template v-else-if="capabilities">
      <p v-if="!capabilities.enabled||!capabilities.capacity" class="hint-box">{{t('paymentConfig.origin.disabled')}}</p>
      <div v-if="capabilities.read_available">
        <p class="hint-box">{{t('paymentConfig.origin.sourceHint')}}</p>
        <p>{{t('paymentConfig.origin.timestampHint')}}</p>
        <SmsParserProfiles :capabilities="capabilities" />
        <ReceivingRealms :capabilities="capabilities" />
        <slot :capabilities="capabilities" />
      </div>
    </template>
  </section>
</template>
