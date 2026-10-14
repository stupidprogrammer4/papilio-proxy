<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useAuth } from "@papilio/auth";
import { item, query, request, type Page, type PaymentReview } from "@papilio/api";
import { faDate, faNumber, toman } from "@papilio/ui";
import {useI18n} from "vue-i18n";
const auth = useAuth();
const {t}=useI18n();
const rows = ref<PaymentReview[]>([]); const page = ref(1); const pages = ref(1); const total = ref(0); const q = ref(""); const status = ref(""); const loading = ref(false); const busy = ref<number | null>(null); const error = ref("");
const statuses: Record<string,string>={waiting:"pending",candidate:"candidate",ambiguous:"ambiguous",stale:"stale",closed:"closed"};
let version = 0;
async function load(): Promise<void> {
  const current = ++version; loading.value = true; error.value = "";
  try { const result = await request<Page<PaymentReview>>(`/v1/admin/payments/reviews?${query({ page: page.value, q: q.value, status: status.value || undefined })}`); if (current !== version) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; total.value = result.meta.pager?.total_items ?? 0; }
  catch (cause) { if (current === version) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (current === version) loading.value = false; }
}
async function check(id: number): Promise<void> {
  busy.value = id; error.value = "";
  try { await item(`/v1/admin/payments/reviews/${id}/check`, "POST"); await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = null; }
}
watch([q, status], () => { page.value = 1; void load(); });
onMounted(load);
</script>
<template>
  <section class="card" :aria-label="t('automation.payments.title')">
    <div class="card-pad"><h2>{{t('automation.payments.title')}}</h2><p class="subtitle">{{t('automation.payments.description')}}</p><div class="toolbar"><label class="field"><span>{{t('automation.payments.search')}}</span><input v-model="q" :placeholder="t('automation.payments.customer')" /></label><label class="field"><span>{{t('automation.payments.health')}}</span><select v-model="status" :aria-label="t('automation.payments.health')"><option value="">{{t('automation.payments.all')}}</option><option v-for="(key, value) in statuses" :key="value" :value="value">{{t(`automation.payments.${key}`)}}</option></select></label><button class="btn secondary" @click="load">{{t('automation.payments.refresh')}}</button></div><p v-if="error" class="message error" role="alert">{{ error }}</p></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>{{t('automation.payments.request')}}</th><th>{{t('automation.payments.amount')}}</th><th>{{t('automation.payments.result')}}</th><th>{{t('automation.payments.references')}}</th><th>{{t('automation.payments.lastCheck')}}</th><th>{{t('automation.payments.actions')}}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.topup_id"><td><strong>{{ row.customer_name }}</strong><br />{{t('automation.payments.request')}} {{ faNumber(row.topup_id) }}</td><td class="tabular">{{ toman(row.amount_rial) }}</td><td><span class="badge" :class="row.status === 'closed' ? 'success' : 'warning'">{{ statuses[row.status] ? t(`automation.payments.${statuses[row.status]}`) : t('automation.payments.unknown') }}</span><small v-if="row.competing_topup_count"> · {{ faNumber(row.competing_topup_count) }} {{t('automation.payments.other')}}</small></td><td class="tabular">{{ faNumber(row.candidate_count) }}</td><td>{{ faDate(row.checked_at) }}</td><td><RouterLink class="btn small secondary" :to="{ path: '/payments', query: { topup_id: row.topup_id } }">{{t('automation.payments.open')}}</RouterLink> <button v-if="auth.can('payments', 'manage')" class="btn small secondary" :disabled="busy !== null" @click="check(row.topup_id)">{{t('automation.payments.recheck')}}</button></td></tr></tbody></table><div v-if="loading" class="empty">{{t('automation.payments.loading')}}</div><div v-else-if="!error && !rows.length" class="empty">{{t('automation.payments.empty')}}</div></div>
    <div class="pager"><button :disabled="loading || page <= 1" @click="page--; load()">‹</button><span>{{t('automation.payments.page',{page:faNumber(page),total:faNumber(total)})}}</span><button :disabled="loading || page >= pages" @click="page++; load()">›</button></div>
  </section>
</template>
