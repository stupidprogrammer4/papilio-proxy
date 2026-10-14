<script setup lang="ts">
import Modal from "@papilio/ui/Modal.vue";
import CoreRuntimeModal from "../components/CoreRuntimeModal.vue";
import CoreExportModal from "../components/CoreExportModal.vue";
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { item, request, query, type CoreInstance, type NodeEndpoint, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faNumber, faDate } from "@papilio/ui";
import { useI18n } from "vue-i18n";
const route = useRoute(); const auth = useAuth(); const nodeId = Number(route.params.nodeId);
const { t } = useI18n();
const node = ref<NodeEndpoint | null>(null); const rows = ref<CoreInstance[]>([]); const page = ref(1); const pages = ref(1); const q = ref("");
const state = ref<"loading" | "ready" | "error">("loading"); const error = ref(""); const busy = ref(false); const code = ref(""); const label = ref(""); const kind = ref<CoreInstance["kind"]>("xray");
const kinds: Record<CoreInstance["kind"], string> = { xray: "Xray", sing_box: "Sing-box", wireguard: "WireGuard", openvpn: "OpenVPN", hysteria: "Hysteria" };
async function load(): Promise<void> {
  state.value = "loading"; error.value = ""; const requested = page.value;
  try { const result = await request<Page<CoreInstance>>(`/v1/admin/network/nodes/${nodeId}/cores?${query({ page: requested, q: q.value })}`); if (requested !== page.value) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; state.value = "ready"; }
  catch (cause) { state.value = "error"; error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
async function create(): Promise<void> {
  busy.value = true; error.value = "";
  try { await item<CoreInstance>(`/v1/admin/network/nodes/${nodeId}/cores`, "POST", { code: code.value, label: label.value, kind: kind.value }); code.value = ""; label.value = ""; page.value = 1; await load(); createOpen.value=false; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; } finally { busy.value = false; }
}
onMounted(async () => { try { node.value = await item<NodeEndpoint>(`/v1/admin/network/nodes/${nodeId}`); await load(); } catch (cause) { state.value = "error"; error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; } });
const createOpen=ref(false);
const runtimeCore = ref<CoreInstance | null>(null);
function closeRuntime(): void { runtimeCore.value = null; void load(); }
const exportCore = ref<CoreInstance | null>(null);
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">{{ t('network.coresEyebrow') }}</p><h1>{{ t('network.coresTitle', { node: node?.label ?? t('network.nodeFallback') }) }}</h1><p class="subtitle">{{ t('network.coresDescription') }}</p></div><RouterLink class="btn secondary" to="/network">{{ t('network.nodes') }}</RouterLink><button v-if="auth.can('network','create')" class="btn" :disabled="busy" @click="createOpen=true">{{ t('network.addCore') }}</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p>
  <p class="hint-box">{{ t('network.coresHint') }}</p>
  <div class="split"><section class="card card-pad"><form class="toolbar" @submit.prevent="page = 1; load()"><label class="field"><span>{{ t('network.searchCores') }}</span><input v-model="q" /></label><button class="btn secondary">{{ t('network.search') }}</button></form><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t('network.core') }}</th><th>{{ t('network.type') }}</th><th>{{ t('network.lastReportedState') }}</th><th>{{ t('network.configurations') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.label }}<br /><small>{{ row.code }}</small></td><td>{{ kinds[row.kind] }}</td><td><template v-if="row.runtime"><span class="badge">{{row.runtime.observed_status}}</span><br /><small>{{row.runtime.last_observed_at ? faDate(row.runtime.last_observed_at) : t('network.noObservation')}}</small><br /><span v-if="row.runtime.automation_paused" class="badge warning">{{ t('network.provisioningPaused') }}</span><br /><small>{{ t('network.appliedDesired', { applied: row.runtime.applied_revision_id ?? t('network.none'), desired: row.runtime.desired_revision_id ?? t('network.none') }) }}</small></template><span v-else class="badge">{{ t('network.notObserved') }}</span></td><td><RouterLink v-if="row.supported_protocols.length > 0" class="btn small secondary" :to="`/network/${nodeId}/cores/${row.id}/configurations`">{{ t('network.manageConfigurations') }}</RouterLink><span v-else class="badge warning">{{ t('network.exportUnavailable') }}</span><button v-if="auth.can('network','create') && auth.can('network','manage')" class="btn small secondary" @click="exportCore=row">{{ t('network.exportCore') }}</button><button class="btn small secondary" @click="runtimeCore=row">{{ t('network.runtimeControl') }}</button></td></tr></tbody></table></div><p v-if="state === 'loading'">{{ t('network.loading') }}</p><p v-else-if="state === 'ready' && !rows.length">{{ t('network.coresEmpty') }}</p><button v-if="state === 'error'" class="btn secondary" @click="load">{{ t('network.retry') }}</button><div class="pager"><button :disabled="page <= 1" :aria-label="t('network.previousPage')" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages" :aria-label="t('network.nextPage')" @click="page++; load()">›</button></div></section>
  <CoreRuntimeModal :core="runtimeCore" @close="closeRuntime" />
  <CoreExportModal :core="exportCore" @close="exportCore=null" />
  <Modal v-if="node && auth.can('network', 'create')" v-model="createOpen" :title="t('network.createCoreTitle')" :busy="busy" wide><p v-if="error" class="message error" role="alert">{{error}}</p><form class="form-grid" @submit.prevent="create"><label class="field"><span>{{ t('network.coreCodeOnNode') }}</span><input v-model="code" required minlength="2" pattern="[A-Za-z0-9_-]+" dir="ltr" /></label><label class="field"><span>{{ t('network.coreLabel') }}</span><input v-model="label" required minlength="2" /></label><label class="field"><span>{{ t('network.coreType') }}</span><select v-model="kind"><option v-for="(name, key) in kinds" :key="key" :value="key">{{ name }}</option></select></label><button class="btn" :disabled="busy">{{ t('network.createDraft') }}</button></form></Modal></div>
</template>
