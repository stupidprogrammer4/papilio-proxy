<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onMounted, ref, watch } from "vue";
import { useAuth } from "@papilio/auth";
import { item, query, request, type Page, type Subscription, type SubscriptionControlRecord } from "@papilio/api";
import { faDate, faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";
const props = defineProps<{ subscription: Subscription }>();
const { t } = useI18n();
const emit = defineEmits<{ changed: [value: Subscription] }>();
const auth = useAuth(); const reason = ref(""); const clock = ref<"continue" | "pause" | "">("");
const attemptKey = ref(""); const records = ref<SubscriptionControlRecord[]>([]); const page = ref(1); const pages = ref(1); const total = ref(0); const loading = ref(false); const readError = ref(""); let readVersion = 0;
const busy = ref(false); const error = ref(""); const notice = ref("");
watch(() => props.subscription.id, () => { reason.value = ""; error.value = ""; notice.value = ""; attemptKey.value = ""; clock.value=""; records.value=[]; page.value=1; void loadRecords(); });
async function loadRecords(): Promise<void> {
  const id=props.subscription.id, version=++readVersion; loading.value=true; readError.value="";
  try { const result = await request<Page<SubscriptionControlRecord>>(`/v1/admin/subscriptions/${id}/controls?${query({page:page.value})}`); if(version!==readVersion || props.subscription.id!==id) return; records.value=result.data; pages.value=result.meta.pager?.total_pages ?? 1; total.value=result.meta.pager?.total_items ?? 0; }
  catch(cause) { if(version===readVersion && props.subscription.id===id) readError.value=cause instanceof Error ? cause.message : t("subscriptionControl.operationFailed"); }
  finally { if(version===readVersion) loading.value=false; }
}
watch([reason, clock], () => { if(!busy.value) attemptKey.value=""; });
onMounted(loadRecords);
async function act(operation: "suspension" | "resumption"): Promise<void> {
  const id = props.subscription.id;
  if (busy.value || !auth.can("subscriptions", "update") || reason.value.trim().length < 3) return;
  if(operation === "suspension" && !clock.value) return;
  if(!attemptKey.value) attemptKey.value=newRequestKey();
  busy.value = true; error.value = ""; notice.value = "";
  try { const result = await item<Subscription>(`/v1/admin/subscriptions/${id}/${operation}`, "PUT", { request_key: attemptKey.value, reason: reason.value.trim(), ...(operation === "suspension" ? { clock: clock.value } : {}) });
    if (props.subscription.id !== id) return;
    emit("changed", result); reason.value = ""; attemptKey.value=""; await loadRecords(); notice.value = operation === "suspension" ? t("subscriptionControl.suspended") : t("subscriptionControl.resumed");
  } catch(cause) { if (props.subscription.id === id) error.value = cause instanceof Error ? cause.message : t("subscriptionControl.operationFailed"); }
  finally { busy.value = false; }
}
</script>
<template>
  <section class="form-grid" style="margin-top:20px"><h3>{{ t('subscriptionControl.title') }}</h3>
    <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
    <template v-if="subscription.suspended_at"><div class="detail-line"><span>{{ t('subscriptionControl.suspendedAt') }}</span><strong>{{ faDate(subscription.suspended_at) }}</strong></div><p class="hint-box">{{ subscription.suspension_reason }} · {{ subscription.suspension_clock === 'pause' ? t('subscriptionControl.pausedExpiry') : t('subscriptionControl.runningExpiry') }}</p><p v-if="subscription.status === 'revoking'" class="hint-box">{{ t('subscriptionControl.revoking') }}</p></template>
    <form v-if="auth.can('subscriptions','update') && ['active','suspended'].includes(subscription.status)" class="form-grid" @submit.prevent="act(subscription.status === 'active' ? 'suspension' : 'resumption')"><label v-if="subscription.status === 'active'" class="field"><span>{{ t('subscriptionControl.expiryBehavior') }}</span><select v-model="clock" required :disabled="busy"><option value="" disabled>{{ t('subscriptionControl.selectClock') }}</option><option value="continue">{{ t('subscriptionControl.keepRunning') }}</option><option value="pause">{{ t('subscriptionControl.pauseUntilResumed') }}</option></select></label><label class="field"><span>{{ subscription.status === 'active' ? t('subscriptionControl.suspensionReason') : t('subscriptionControl.continueReason') }}</span><textarea v-model="reason" minlength="3" maxlength="250" required :disabled="busy" /></label><button class="btn secondary" :disabled="busy || reason.trim().length < 3 || (subscription.status === 'active' && !clock)">{{ subscription.status === 'active' ? t('subscriptionControl.requestSuspension') : t('subscriptionControl.resume') }}</button></form>
    <h3>{{ t('subscriptionControl.history') }}</h3><p v-if="readError" class="message error" role="alert">{{ readError }} <button class="btn small secondary" @click="loadRecords">{{ t('subscriptionControl.retry') }}</button></p><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t('subscriptionControl.time') }}</th><th>{{ t('subscriptionControl.action') }}</th><th>{{ t('subscriptionControl.reason') }}</th><th>{{ t('subscriptionControl.staff') }}</th><th>{{ t('subscriptionControl.clockPolicy') }}</th></tr></thead><tbody><tr v-for="record in records" :key="record.id"><td>{{ faDate(record.created_at) }}</td><td>{{ record.action==='suspend'?t('subscriptionControl.suspension'):t('subscriptionControl.continue') }}</td><td>{{ record.reason }}</td><td>{{ record.staff_id !== null ? t('subscriptionControl.operator', { id: faNumber(record.staff_id) }) : t('subscriptionControl.resellerMember', { id: faNumber(record.actor_account_id) }) }}</td><td>{{ record.clock==='pause'?t('subscriptionControl.pausedClock'):t('subscriptionControl.runningClock') }}</td></tr></tbody></table><div v-if="loading" class="empty">{{ t('subscriptionControl.loading') }}</div><div v-else-if="!records.length && !readError" class="empty">{{ t('subscriptionControl.empty') }}</div></div><div class="pager"><button :disabled="page<=1 || loading" :aria-label="t('subscriptionControl.previousPage')" @click="page--; loadRecords()">‹</button><span>{{ t('subscriptionControl.pageCount', { page: faNumber(page), total: faNumber(total) }) }}</span><button :disabled="page>=pages || loading" :aria-label="t('subscriptionControl.nextPage')" @click="page++; loadRecords()">›</button></div>
  </section>
</template>
