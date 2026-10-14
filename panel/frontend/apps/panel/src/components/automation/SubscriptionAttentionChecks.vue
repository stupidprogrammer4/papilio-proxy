<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useAuth } from "@papilio/auth";
import { item, query, request, type Page, type SubscriptionAttention } from "@papilio/api";
import { faDate, faNumber, toman } from "@papilio/ui";
import {useI18n} from "vue-i18n";
const auth = useAuth();
const {t}=useI18n();
const rows = ref<SubscriptionAttention[]>([]); const page = ref(1); const pages = ref(1); const total = ref(0); const q = ref(""); const status = ref(""); const loading = ref(false); const busy = ref<number | null>(null); const error = ref("");
const labels=["renewal_unavailable","clear","quota_exhausted","expiry_soon","expired","renewal_unfunded","provisioning_delayed","provisioning_failed"] as const;
let version = 0;
async function load(): Promise<void> {
  const current = ++version; loading.value = true; error.value = "";
  try { const result = await request<Page<SubscriptionAttention>>(`/v1/admin/subscriptions/attention?${query({ page: page.value, q: q.value, status: status.value || undefined })}`); if (current !== version) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; total.value = result.meta.pager?.total_items ?? 0; }
  catch (cause) { if (current === version) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (current === version) loading.value = false; }
}
async function check(id: number): Promise<void> {
  busy.value = id; error.value = "";
  try { await item(`/v1/admin/subscriptions/attention/${id}/check`, "POST"); await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = null; }
}
watch([q, status], () => { page.value = 1; void load(); });
onMounted(load);
</script>
<template>
  <section class="card" :aria-label="t('automation.attention.title')">
    <div class="card-pad"><h2>{{t('automation.attention.title')}}</h2><p class="subtitle">{{t('automation.attention.description')}}</p><div class="toolbar"><label class="field"><span>{{t('automation.attention.search')}}</span><input v-model="q" :placeholder="t('automation.attention.customer')" /></label><label class="field"><span>{{t('automation.attention.status')}}</span><select v-model="status" :aria-label="t('automation.attention.status')"><option value="">{{t('automation.attention.all')}}</option><option v-for="value in labels" :key="value" :value="value">{{t(`automation.attention.${value}`)}}</option></select></label><button class="btn secondary" @click="load">{{t('automation.attention.refresh')}}</button></div><p v-if="error" class="message error" role="alert">{{ error }}</p></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>{{t('automation.attention.customerSubscription')}}</th><th>{{t('automation.attention.attentionStatus')}}</th><th>{{t('automation.attention.expiry')}}</th><th>{{t('automation.attention.renewal')}}</th><th>{{t('automation.attention.walletPrice')}}</th><th>{{t('automation.attention.lastCheck')}}</th><th>{{t('automation.attention.actions')}}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.subscription_id"><td><strong>{{ row.customer_name }}</strong><br />{{t('automation.attention.subscription')}} {{ faNumber(row.subscription_id) }}</td><td><span class="badge" :class="row.status === 'clear' ? 'success' : 'warning'">{{t(`automation.attention.${labels.includes(row.status as typeof labels[number])?row.status:'unknown'}`)}}</span></td><td>{{ faDate(row.expires_at) }}</td><td>{{ row.auto_renew ? t('automation.attention.automatic') : t('automation.attention.manual') }}</td><td class="tabular">{{ toman(row.wallet_balance_rial) }} / {{ row.renewal_price_rial===null?t('automation.attention.needsRecheck'):toman(row.renewal_price_rial) }}</td><td>{{ faDate(row.checked_at) }}</td><td><RouterLink class="btn small secondary" :to="{ path: '/subscriptions', query: { subscription_id: row.subscription_id } }">{{t('automation.attention.record')}}</RouterLink> <RouterLink v-if="auth.can('payments')&&row.payer_customer_id!==null" class="btn small secondary" :to="`/customers/${row.payer_customer_id}/wallet`">{{t('automation.attention.payingWallet')}}</RouterLink> <button v-if="auth.can('subscriptions', 'manage')" class="btn small secondary" :disabled="busy !== null" @click="check(row.subscription_id)">{{t('automation.attention.recheck')}}</button></td></tr></tbody></table><div v-if="loading" class="empty">{{t('automation.attention.loading')}}</div><div v-else-if="!error && !rows.length" class="empty">{{t('automation.attention.empty')}}</div></div>
    <div class="pager"><button :disabled="loading || page <= 1" @click="page--; load()">‹</button><span>{{t('automation.attention.page',{page:faNumber(page),total:faNumber(total)})}}</span><button :disabled="loading || page >= pages" @click="page++; load()">›</button></div>
  </section>
</template>
