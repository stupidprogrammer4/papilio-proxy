<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useAuth } from "@papilio/auth";
import { ApiError, item, type SmsOriginCapabilities } from "@papilio/api";
import SmsParserProfiles from "./SmsParserProfiles.vue";
import ReceivingRealms from "./ReceivingRealms.vue";
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
    else { state.value="error"; error.value=cause instanceof Error?cause.message:"Could not read SMS capabilities."; }
  }
}
onMounted(load);
onUnmounted(()=>{alive=false;++sequence;});
</script>
<template>
  <section class="card card-pad" aria-label="SMS parsing and source identity">
    <div class="page-head"><div><p class="eyebrow">SMS EVIDENCE</p><h2>Parsing and source identity</h2><p class="subtitle">Manage how deposits are recognized and linked to receiving accounts.</p></div><button class="btn secondary" :disabled="state==='loading'" @click="load">Refresh capabilities</button></div>
    <p v-if="state==='loading'" role="status">Loading SMS capabilities…</p>
    <p v-else-if="state==='unavailable'" class="hint-box">SMS parser and source-identity management is unavailable. Existing payment review remains available.</p>
    <p v-else-if="state==='error'" class="message error" role="alert">{{error}}</p>
    <template v-else-if="capabilities">
      <p v-if="!capabilities.enabled||!capabilities.capacity" class="hint-box">SMS parser and source-identity management is disabled in the current operational policy. Existing payment review remains available.</p>
      <div v-if="capabilities.read_available">
        <p class="hint-box">Source metadata is declared by your enrolled webhook sender. It authenticates that sender; it does not independently verify bank settlement. Forwarded, imported and manually entered messages require review.</p>
        <p>Trusted-origin matching requires the original provider timestamp, original sender, source kind and canonicalization revision. A forwarding timestamp cannot replace the original timestamp.</p>
        <SmsParserProfiles :capabilities="capabilities" />
        <ReceivingRealms :capabilities="capabilities" />
        <slot :capabilities="capabilities" />
      </div>
    </template>
  </section>
</template>
