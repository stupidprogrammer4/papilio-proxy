<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useAuth } from "@papilio/auth";
import { item, query, request, type Page, type SubscriptionAttention } from "@papilio/api";
import { faDate, faNumber, toman } from "@papilio/ui";
const auth = useAuth();
const rows = ref<SubscriptionAttention[]>([]); const page = ref(1); const pages = ref(1); const total = ref(0); const q = ref(""); const status = ref(""); const loading = ref(false); const busy = ref<number | null>(null); const error = ref("");
const labels: Record<string, string> = {"renewal_unavailable": "Renewal is unavailable under the current policy or agreement", "clear": "No alerts", "quota_exhausted": "Quota exhausted", "expiry_soon": "Expiry approaching", "expired": "Expired", "renewal_unfunded": "Insufficient renewal balance", "provisioning_delayed": "Provisioning delayed", "provisioning_failed": "Provisioning failed"};
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
  <section class="card" aria-label="Subscriptions needing attention">
    <div class="card-pad"><h2>Subscriptions needing attention</h2><p class="subtitle">Review expiry, wallet balance and provisioning alerts. Each record shows when it was checked.</p><div class="toolbar"><label class="field"><span>Search</span><input v-model="q" placeholder="Customer name" /></label><label class="field"><span>Health status</span><select v-model="status" aria-label="Health status"><option value="">All</option><option v-for="(label, value) in labels" :key="value" :value="value">{{ label }}</option></select></label><button class="btn secondary" @click="load">Refresh</button></div><p v-if="error" class="message error" role="alert">{{ error }}</p></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Customer and subscription</th><th>Attention status</th><th>Expiry</th><th>Renewal</th><th>Wallet balance / renewal price</th><th>Last check</th><th>Actions</th></tr></thead><tbody><tr v-for="row in rows" :key="row.subscription_id"><td><strong>{{ row.customer_name }}</strong><br />Subscription {{ faNumber(row.subscription_id) }}</td><td><span class="badge" :class="row.status === 'clear' ? 'success' : 'warning'">{{ labels[row.status] ?? 'Unknown' }}</span></td><td>{{ faDate(row.expires_at) }}</td><td>{{ row.auto_renew ? 'Automatic' : 'Manual' }}</td><td class="tabular">{{ toman(row.wallet_balance_rial) }} / {{ row.renewal_price_rial===null?'Needs recheck':toman(row.renewal_price_rial) }}</td><td>{{ faDate(row.checked_at) }}</td><td><RouterLink class="btn small secondary" :to="{ path: '/subscriptions', query: { subscription_id: row.subscription_id } }">Subscription record</RouterLink> <RouterLink v-if="auth.can('payments')&&row.payer_customer_id!==null" class="btn small secondary" :to="`/customers/${row.payer_customer_id}/wallet`">Paying wallet</RouterLink> <button v-if="auth.can('subscriptions', 'manage')" class="btn small secondary" :disabled="busy !== null" @click="check(row.subscription_id)">Recheck</button></td></tr></tbody></table><div v-if="loading" class="empty">Loading checks…</div><div v-else-if="!error && !rows.length" class="empty">No checks recorded.</div></div>
    <div class="pager"><button :disabled="loading || page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} Result</span><button :disabled="loading || page >= pages" @click="page++; load()">›</button></div>
  </section>
</template>
