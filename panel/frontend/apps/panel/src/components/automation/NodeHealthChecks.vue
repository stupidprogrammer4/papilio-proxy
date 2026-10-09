<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useAuth } from "@papilio/auth";
import { item, query, request, type Page, type NodeHealth } from "@papilio/api";
import { faDate, faDigits, faNumber } from "@papilio/ui";
const auth = useAuth();
const rows = ref<NodeHealth[]>([]); const page = ref(1); const pages = ref(1); const total = ref(0); const q = ref(""); const status = ref(""); const loading = ref(false); const busy = ref<number | null>(null); const error = ref("");
const labels: Record<string, string> = {"disabled": "Disabled by owner", "unknown": "No reports", "stale": "Stale report", "insufficient": "Insufficient samples", "healthy": "Healthy samples", "degraded": "Poor quality", "unreachable": "Failed samples"};
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
  <section class="card" aria-label="Node health">
    <div class="card-pad"><h2>Node health</h2><p class="subtitle">Health is calculated from authenticated probe reports. Results describe the sampled network and time. Node access is controlled separately.</p><div class="toolbar"><label class="field"><span>Search</span><input v-model="q" placeholder="Node name or code" /></label><label class="field"><span>Health status</span><select v-model="status" aria-label="Health status"><option value="">All</option><option v-for="(label, value) in labels" :key="value" :value="value">{{ label }}</option></select></label><button class="btn secondary" @click="load">Refresh</button></div><p v-if="error" class="message error" role="alert">{{ error }}</p></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Node</th><th>Last observation</th><th>Successful / samples</th><th>Average latency</th><th>Last sample</th><th>Last check</th><th>Actions</th></tr></thead><tbody><tr v-for="row in rows" :key="row.node_id"><td><strong>{{ row.label }}</strong><br /><small>{{ faDigits(row.code) }}</small></td><td><span class="badge" :class="row.status === 'healthy' ? 'success' : row.status === 'unreachable' ? 'danger' : 'warning'">{{ labels[row.status] ?? 'Unknown' }}</span></td><td class="tabular">{{ faNumber(row.successful_count) }} / {{ faNumber(row.sample_count) }}</td><td class="tabular">{{ row.average_latency_ms === null ? '—' : faNumber(row.average_latency_ms) + ' ms' }}</td><td>{{ row.last_sample_at ? faDate(row.last_sample_at) : '—' }}</td><td>{{ faDate(row.checked_at) }}</td><td><RouterLink class="btn small secondary" :to="`/network/${row.node_id}/configurations`">Configuration Node</RouterLink> <button v-if="auth.can('network', 'manage')" class="btn small secondary" :disabled="busy !== null" @click="check(row.node_id)">Recheck</button></td></tr></tbody></table><div v-if="loading" class="empty">Loading checks…</div><div v-else-if="!error && !rows.length" class="empty">No checks recorded.</div></div>
    <div class="pager"><button :disabled="loading || page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} Result</span><button :disabled="loading || page >= pages" @click="page++; load()">›</button></div>
  </section>
</template>
