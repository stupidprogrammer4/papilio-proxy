<script setup lang="ts">
import { ref, watch } from "vue";
import { item, request, query, type Page, type UsageSummary, type UsageEvent, type UsageGrant } from "@papilio/api";
import { faNumber, faDate, faDigits, asciiDigits } from "@papilio/ui";
import { useI18n } from "vue-i18n";
const props = defineProps<{ subscriptionId?: number }>();
const { t } = useI18n();
const summary = ref<UsageSummary | null>(null); const events = ref<UsageEvent[]>([]); const grants = ref<UsageGrant[]>([]);
const page = ref(1); const pages = ref(1); const grantPage = ref(1); const grantPages = ref(1); const since = ref(""); const until = ref("");
const loading = ref(false); const error = ref(""); let version = 0;
function timestamp(value: string): string | undefined {
  const normalized = asciiDigits(value).trim(); if (!normalized) return undefined;
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?$/.test(normalized)) throw new Error(t("usageRecords.gregorianDateRequired"));
  const iso = normalized.replace(" ", "T") + (normalized.length === 16 ? ":00Z" : "Z"); const date = new Date(iso);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0,19) !== iso.slice(0,19)) throw new Error(t("usageRecords.invalidDate"));
  return date.toISOString();
}
function input(event: Event, name: "since" | "until"): void { const target = event.target as HTMLInputElement; const value = asciiDigits(target.value); if (name === "since") since.value = value; else until.value = value; target.value = faDigits(value); }
async function load(): Promise<void> {
  const read = ++version; const id = props.subscriptionId; loading.value = true; error.value = "";
  try {
    const start = timestamp(since.value); const end = timestamp(until.value); if (start && end && start > end) throw new Error(t("usageRecords.endAfterStart"));
    const filters = { subscription_id: id, since: start, until: end };
    const [totals, samples, budgets] = await Promise.all([item<UsageSummary>(`/v1/admin/usage/summary?${query(filters)}`), request<Page<UsageEvent>>(`/v1/admin/usage/events?${query({ ...filters, page: page.value })}`), request<Page<UsageGrant>>(`/v1/admin/usage/grants?${query({ subscription_id: id, page: grantPage.value })}`)]);
    if (read !== version || id !== props.subscriptionId) return; summary.value = totals; events.value = samples.data; pages.value = samples.meta.pager?.total_pages ?? 1; grants.value = budgets.data; grantPages.value = budgets.meta.pager?.total_pages ?? 1;
  } catch(cause) { if (read === version) error.value = cause instanceof Error ? cause.message : t("usageRecords.operationFailed"); }
  finally { if (read === version) loading.value = false; }
}
function filter(): void { page.value = 1; void load(); }
watch(() => props.subscriptionId, () => { version++; summary.value = null; events.value = []; grants.value = []; page.value = 1; grantPage.value = 1; void load(); }, { immediate: true });
</script>
<template>
  <section class="form-grid">
    <h2>{{ t('usageRecords.title') }}</h2><p>{{ t('usageRecords.description') }}</p>
    <form class="toolbar" @submit.prevent="filter"><label class="field"><span>{{ t('usageRecords.from') }}</span><input :value="faDigits(since)" :placeholder="t('usageRecords.fromPlaceholder')" @input="input($event, 'since')" /></label><label class="field"><span>{{ t('usageRecords.to') }}</span><input :value="faDigits(until)" :placeholder="t('usageRecords.toPlaceholder')" @input="input($event, 'until')" /></label><button class="btn secondary" :disabled="loading">{{ t('usageRecords.applyWindow') }}</button></form>
    <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="error && summary" class="hint-box">{{ t('usageRecords.lastRead') }}</p><p v-if="loading">{{ t('usageRecords.loading') }}</p>
    <div v-if="summary" class="stats"><div class="stat"><span>{{ t('usageRecords.upload') }}</span><strong class="value tabular">{{ faNumber(summary.upload_bytes) }}</strong></div><div class="stat"><span>{{ t('usageRecords.download') }}</span><strong class="value tabular">{{ faNumber(summary.download_bytes) }}</strong></div><div class="stat"><span>{{ t('usageRecords.totalUsage') }}</span><strong class="value tabular">{{ faNumber(summary.total_bytes) }}</strong></div></div>
    <p v-if="!loading && !error && !events.length">{{ t('usageRecords.emptyEvents') }}</p>
    <div class="table-wrap"><table v-if="events.length" class="data-table"><thead><tr><th>{{ t('usageRecords.time') }}</th><th>{{ t('usageRecords.subscription') }}</th><th>{{ t('usageRecords.node') }}</th><th>{{ t('usageRecords.period') }}</th><th>{{ t('usageRecords.newUsage') }}</th><th>{{ t('usageRecords.finalReport') }}</th></tr></thead><tbody><tr v-for="row in events" :key="row.id"><td>{{ faDate(row.sampled_at) }}</td><td>{{ faNumber(row.subscription_id) }}</td><td>{{ faNumber(row.node_id) }}</td><td>{{ faNumber(row.generation) }}</td><td class="tabular">{{ faNumber(row.delta_bytes) }}</td><td>{{ row.final ? t('usageRecords.yes') : t('usageRecords.no') }}</td></tr></tbody></table></div>
    <div class="pager"><button :disabled="page <= 1 || loading" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages || loading" @click="page++; load()">›</button></div>
    <h3>{{ t('usageRecords.grantsTitle') }}</h3><p>{{ t('usageRecords.grantsNote') }}</p>
    <div class="table-wrap"><table v-if="grants.length" class="data-table"><thead><tr><th>{{ t('usageRecords.grant') }}</th><th>{{ t('usageRecords.node') }}</th><th>{{ t('usageRecords.method') }}</th><th>{{ t('usageRecords.allocated') }}</th><th>{{ t('usageRecords.usage') }}</th><th>{{ t('usageRecords.validity') }}</th><th>{{ t('usageRecords.status') }}</th></tr></thead><tbody><tr v-for="row in grants" :key="row.id"><td>{{ faNumber(row.id) }}</td><td>{{ faNumber(row.node_id) }}</td><td>{{ row.mode === 'reserved' ? t('usageRecords.sharedReservation') : t('usageRecords.report') }}</td><td>{{ faNumber(row.allocated_bytes) }}</td><td :class="{ 'message error': row.mode === 'reserved' && row.upload_bytes + row.download_bytes > row.allocated_bytes }">{{ faNumber(row.upload_bytes + row.download_bytes) }}</td><td>{{ faDate(row.valid_until) }}</td><td>{{ row.is_closed ? t('usageRecords.closed') : new Date(row.valid_until).getTime() <= Date.now() ? t('usageRecords.expiredAwaiting') : t('usageRecords.open') }}</td></tr></tbody></table></div>
    <p v-if="!loading && !error && !grants.length">{{ t('usageRecords.emptyGrants') }}</p><div class="pager"><button :disabled="grantPage <= 1 || loading" @click="grantPage--; load()">‹</button><span>{{ faNumber(grantPage) }}</span><button :disabled="grantPage >= grantPages || loading" @click="grantPage++; load()">›</button></div>
  </section>
</template>
