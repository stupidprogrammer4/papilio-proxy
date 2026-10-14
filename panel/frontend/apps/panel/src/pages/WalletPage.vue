<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { item, request, query, type Page, type WalletBalance, type WalletEntry } from "@papilio/api";
import { faDate, faDigits, faNumber, toman } from "@papilio/ui";
const { t } = useI18n();
const route = useRoute();
const customerId = computed(() => Number(route.params.customerId));
const rows = ref<WalletEntry[]>([]); const balance = ref<number | null>(null); const page = ref(1); const pages = ref(1); const total = ref(0); const reason = ref(""); const loading = ref(false); const error = ref("");
const reasons = computed<Record<string, string>>(() => ({ approved_topup: t("wallet.reasons.approvedTopup"), purchase: t("wallet.reasons.purchase"), auto_renewal: t("wallet.reasons.autoRenewal"), provision_refund: t("wallet.reasons.provisionRefund") }));
let version = 0;
async function load(): Promise<void> {
  const current = ++version; loading.value = true; error.value = "";
  if (!Number.isSafeInteger(customerId.value) || customerId.value <= 0) { error.value = t("wallet.invalidCustomer"); loading.value = false; return; }
  try {
    const [wallet, entries] = await Promise.all([item<WalletBalance>(`/v1/admin/payments/wallets/${customerId.value}`), request<Page<WalletEntry>>(`/v1/admin/payments/wallets/${customerId.value}/entries?${query({ page: page.value, reason: reason.value || undefined })}`)]);
    if (current !== version) return; balance.value = wallet.balance_rial; rows.value = entries.data; total.value = entries.meta.pager?.total_items ?? 0; pages.value = entries.meta.pager?.total_pages ?? 1;
  } catch (cause) { if (current === version) error.value = cause instanceof Error ? cause.message : t("wallet.operationFailed"); }
  finally { if (current === version) loading.value = false; }
}
watch(customerId, () => { page.value = 1; rows.value = []; balance.value = null; void load(); }, { immediate: true });
watch(reason, () => { page.value = 1; void load(); });
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">{{ t('wallet.eyebrow', { id: faNumber(customerId) }) }}</p><h1>{{ t('wallet.title') }}</h1><p class="subtitle">{{ t('wallet.description') }}</p></div><button class="btn secondary" @click="load">{{t('wallet.refresh')}}</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p>
  <div class="card"><div class="card-pad"><div class="detail-line"><span>{{t('wallet.balance')}}</span><strong>{{ balance === null ? '—' : toman(balance) }}</strong></div><div class="toolbar"><label class="field"><span>{{t('wallet.entryType')}}</span><select v-model="reason" :aria-label="t('wallet.entryType')"><option value="">{{t('wallet.all')}}</option><option v-for="(label, value) in reasons" :key="value" :value="value">{{ label }}</option></select></label></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>{{t('wallet.time')}}</th><th>{{t('wallet.type')}}</th><th>{{t('wallet.creditDebit')}}</th><th>{{t('wallet.balanceAfter')}}</th><th>{{t('wallet.reference')}}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ faDate(row.created_at) }}</td><td>{{ reasons[row.reason] ?? t('wallet.recorded') }}</td><td class="tabular"><span class="badge" :class="row.amount_rial > 0 ? 'success' : 'danger'">{{ toman(row.amount_rial) }}</span></td><td class="tabular">{{ toman(row.balance_after_rial) }}</td><td>{{ faDigits(row.reference) }}</td></tr></tbody></table><div v-if="loading" class="empty">{{t('wallet.loadingHistory')}}</div><div v-else-if="!error && !rows.length" class="empty">{{t('wallet.empty')}}</div></div><div class="pager"><button :disabled="loading || page <= 1" :aria-label="t('wallet.previousPage')" @click="page--; load()">‹</button><span>{{ t('wallet.pageCount', {page:faNumber(page),total:faNumber(total)}) }}</span><button :disabled="loading || page >= pages" :aria-label="t('wallet.nextPage')" @click="page++; load()">›</button></div></div>
</template>
