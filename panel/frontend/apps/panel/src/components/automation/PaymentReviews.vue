<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useAuth } from "@papilio/auth";
import { item, query, request, type Page, type PaymentReview } from "@papilio/api";
import { faDate, faNumber, toman } from "@papilio/ui";
const auth = useAuth();
const rows = ref<PaymentReview[]>([]); const page = ref(1); const pages = ref(1); const total = ref(0); const q = ref(""); const status = ref(""); const loading = ref(false); const busy = ref<number | null>(null); const error = ref("");
const labels: Record<string, string> = {"waiting": "Pending SMS", "candidate": "Awaiting approval", "ambiguous": "Ambiguous match", "stale": "Stale request", "closed": "Review complete"};
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
  <section class="card" aria-label="Payment reconciliation">
    <div class="card-pad"><h2>Payment reconciliation</h2><p class="subtitle">Review amount and SMS reference matches. Enrolled-device automatic approval follows the configured trust policy; ambiguous matches need manual settlement review.</p><div class="toolbar"><label class="field"><span>Search</span><input v-model="q" placeholder="Customer name" /></label><label class="field"><span>Health status</span><select v-model="status" aria-label="Health status"><option value="">All</option><option v-for="(label, value) in labels" :key="value" :value="value">{{ label }}</option></select></label><button class="btn secondary" @click="load">Refresh</button></div><p v-if="error" class="message error" role="alert">{{ error }}</p></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Request and customer</th><th>Amount</th><th>Result</th><th>Suggested references</th><th>Last check</th><th>Actions</th></tr></thead><tbody><tr v-for="row in rows" :key="row.topup_id"><td><strong>{{ row.customer_name }}</strong><br />Request {{ faNumber(row.topup_id) }}</td><td class="tabular">{{ toman(row.amount_rial) }}</td><td><span class="badge" :class="row.status === 'closed' ? 'success' : 'warning'">{{ labels[row.status] ?? 'Unknown' }}</span><small v-if="row.competing_topup_count"> · {{ faNumber(row.competing_topup_count) }} other requests with this amount</small></td><td class="tabular">{{ faNumber(row.candidate_count) }}</td><td>{{ faDate(row.checked_at) }}</td><td><RouterLink class="btn small secondary" :to="{ path: '/payments', query: { topup_id: row.topup_id } }">PAYMENT RECONCILIATION</RouterLink> <button v-if="auth.can('payments', 'manage')" class="btn small secondary" :disabled="busy !== null" @click="check(row.topup_id)">Recheck</button></td></tr></tbody></table><div v-if="loading" class="empty">Loading checks…</div><div v-else-if="!error && !rows.length" class="empty">No checks recorded.</div></div>
    <div class="pager"><button :disabled="loading || page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} Result</span><button :disabled="loading || page >= pages" @click="page++; load()">›</button></div>
  </section>
</template>
