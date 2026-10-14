<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useAuth } from "@papilio/auth";
import { item, query, request, type Page, type NodeHealth } from "@papilio/api";
import { faDate, faDigits, faNumber } from "@papilio/ui";
import {useI18n} from "vue-i18n";
const auth = useAuth();
const {t}=useI18n();
const rows = ref<NodeHealth[]>([]); const page = ref(1); const pages = ref(1); const total = ref(0); const q = ref(""); const status = ref(""); const loading = ref(false); const busy = ref<number | null>(null); const error = ref("");
const statuses: Record<string,string> = {disabled:"disabled",unknown:"unknownStatus",stale:"stale",insufficient:"insufficient",healthy:"healthy",degraded:"degraded",unreachable:"unreachable"};
let version = 0;
async function load(): Promise<void> {
  const current = ++version; loading.value = true; error.value = "";
  try { const result = await request<Page<NodeHealth>>(`/v1/admin/network/health?${query({ page: page.value, q: q.value, status: status.value || undefined })}`); if (current !== version) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; total.value = result.meta.pager?.total_items ?? 0; }
  catch (cause) { if (current === version) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (current === version) loading.value = false; }
}
async function check(id: number): Promise<void> {
  busy.value = id; error.value = "";
  try { await item(`/v1/admin/network/health/${id}/check`, "POST"); await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = null; }
}
watch([q, status], () => { page.value = 1; void load(); });
onMounted(load);
</script>
<template>
  <section class="card" :aria-label="t('automation.nodes.title')">
    <div class="card-pad"><h2>{{t('automation.nodes.title')}}</h2><p class="subtitle">{{t('automation.nodes.description')}}</p><div class="toolbar"><label class="field"><span>{{t('automation.nodes.search')}}</span><input v-model="q" :placeholder="t('automation.nodes.nodeSearch')" /></label><label class="field"><span>{{t('automation.nodes.health')}}</span><select v-model="status" :aria-label="t('automation.nodes.health')"><option value="">{{t('automation.nodes.all')}}</option><option v-for="(key, value) in statuses" :key="value" :value="value">{{t(`automation.nodes.${key}`)}}</option></select></label><button class="btn secondary" @click="load">{{t('automation.nodes.refresh')}}</button></div><p v-if="error" class="message error" role="alert">{{ error }}</p></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>{{t('automation.nodes.node')}}</th><th>{{t('automation.nodes.observation')}}</th><th>{{t('automation.nodes.samples')}}</th><th>{{t('automation.nodes.latency')}}</th><th>{{t('automation.nodes.lastSample')}}</th><th>{{t('automation.nodes.lastCheck')}}</th><th>{{t('automation.nodes.actions')}}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.node_id"><td><strong>{{ row.label }}</strong><br /><small>{{ faDigits(row.code) }}</small></td><td><span class="badge" :class="row.status === 'healthy' ? 'success' : row.status === 'unreachable' ? 'danger' : 'warning'">{{ statuses[row.status] ? t(`automation.nodes.${statuses[row.status]}`) : t('automation.nodes.unknown') }}</span></td><td class="tabular">{{ faNumber(row.successful_count) }} / {{ faNumber(row.sample_count) }}</td><td class="tabular">{{ row.average_latency_ms === null ? '—' : faNumber(row.average_latency_ms) + ' ms' }}</td><td>{{ row.last_sample_at ? faDate(row.last_sample_at) : '—' }}</td><td>{{ faDate(row.checked_at) }}</td><td><RouterLink class="btn small secondary" :to="`/network/${row.node_id}/configurations`">{{t('automation.nodes.configuration')}}</RouterLink> <button v-if="auth.can('network', 'manage')" class="btn small secondary" :disabled="busy !== null" @click="check(row.node_id)">{{t('automation.nodes.recheck')}}</button></td></tr></tbody></table><div v-if="loading" class="empty">{{t('automation.nodes.loading')}}</div><div v-else-if="!error && !rows.length" class="empty">{{t('automation.nodes.empty')}}</div></div>
    <div class="pager"><button :disabled="loading || page <= 1" @click="page--; load()">‹</button><span>{{t('automation.nodes.page',{page:faNumber(page),total:faNumber(total)})}}</span><button :disabled="loading || page >= pages" @click="page++; load()">›</button></div>
  </section>
</template>
