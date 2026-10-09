<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { item, request, query, type Page, type WalletBalance, type WalletEntry } from "@papilio/api";
import { faDate, faDigits, faNumber, toman } from "@papilio/ui";
const route = useRoute();
const customerId = computed(() => Number(route.params.customerId));
const rows = ref<WalletEntry[]>([]); const balance = ref<number | null>(null); const page = ref(1); const pages = ref(1); const total = ref(0); const reason = ref(""); const loading = ref(false); const error = ref("");
const reasons: Record<string, string> = { approved_topup: "Approved top-up", purchase: "Subscription purchase", auto_renewal: "Renewal Automatic", provision_refund: "Provisioning refund" };
let version = 0;
async function load(): Promise<void> {
  const current = ++version; loading.value = true; error.value = "";
  if (!Number.isSafeInteger(customerId.value) || customerId.value <= 0) { error.value = "Invalid customer ID."; loading.value = false; return; }
  try {
    const [wallet, entries] = await Promise.all([item<WalletBalance>(`/v1/admin/payments/wallets/${customerId.value}`), request<Page<WalletEntry>>(`/v1/admin/payments/wallets/${customerId.value}/entries?${query({ page: page.value, reason: reason.value || undefined })}`)]);
    if (current !== version) return; balance.value = wallet.balance_rial; rows.value = entries.data; total.value = entries.meta.pager?.total_items ?? 0; pages.value = entries.meta.pager?.total_pages ?? 1;
  } catch (cause) { if (current === version) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (current === version) loading.value = false; }
}
watch(customerId, () => { page.value = 1; rows.value = []; balance.value = null; void load(); }, { immediate: true });
watch(reason, () => { page.value = 1; void load(); });
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">Wallet for customer {{ faNumber(customerId) }}</p><h1>Wallet activity</h1><p class="subtitle">Top-ups, purchases, renewals and refunds</p></div><button class="btn secondary" @click="load">Refresh</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p>
  <div class="card"><div class="card-pad"><div class="detail-line"><span>Current balance</span><strong>{{ balance === null ? '—' : toman(balance) }}</strong></div><div class="toolbar"><label class="field"><span>Entry type</span><select v-model="reason" aria-label="Entry type"><option value="">All</option><option v-for="(label, value) in reasons" :key="value" :value="value">{{ label }}</option></select></label></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Type</th><th>Credit / debit</th><th>Balance after entry</th><th>Tracking reference</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ faDate(row.created_at) }}</td><td>{{ reasons[row.reason] ?? 'Recorded entries' }}</td><td class="tabular"><span class="badge" :class="row.amount_rial > 0 ? 'success' : 'danger'">{{ toman(row.amount_rial) }}</span></td><td class="tabular">{{ toman(row.balance_after_rial) }}</td><td>{{ faDigits(row.reference) }}</td></tr></tbody></table><div v-if="loading" class="empty">Loading wallet history…</div><div v-else-if="!error && !rows.length" class="empty">No wallet entries match these filters.</div></div><div class="pager"><button :disabled="loading || page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} entries</span><button :disabled="loading || page >= pages" @click="page++; load()">›</button></div></div>
</template>
