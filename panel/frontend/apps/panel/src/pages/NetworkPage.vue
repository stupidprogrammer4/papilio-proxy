<script setup lang="ts">
import Modal from "@papilio/ui/Modal.vue";
import NodeCapabilitiesModal from "../components/NodeCapabilitiesModal.vue";
import { useAuth } from "@papilio/auth";
import { onMounted, ref } from "vue";
import { item, query, request, type NodeEndpoint, type NodeQuality, type Page, type RegisteredNode } from "@papilio/api";
import { faDigits, faNumber } from "@papilio/ui";
import NumField from "@papilio/ui/NumField.vue";

const auth = useAuth();
const rows = ref<NodeEndpoint[]>([]); const total = ref(0); const page = ref(1); const pages = ref(1); const network = ref(""); const quality = ref<NodeQuality[]>([]);
const code = ref(""); const label = ref(""); const publicHost = ref(""); const publicPort = ref(""); const protocol = ref("");
const revealedKey = ref(""); const reveal = ref(false); const error = ref(""); const notice = ref(""); const loading = ref(false); const busy = ref(false);
const protocolLabels: Record<string, string> = { vless_reality: "VLESS + REALITY", vless_tls: "VLESS + TLS", vmess_tls: "VMess + TLS", trojan_tls: "Trojan + TLS", shadowsocks: "Shadowsocks", hysteria2: "Hysteria 2", wireguard: "WireGuard", openvpn: "OpenVPN" };

async function load(): Promise<void> {
  loading.value = true; error.value = "";
  try { const result = await request<Page<NodeEndpoint>>(`/v1/admin/network/nodes?${query({ page: page.value })}`); rows.value = result.data; total.value = result.meta.pager?.total_items ?? 0; pages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { loading.value = false; }
}
async function loadQuality(): Promise<void> {
  if (network.value.trim().length < 2) return;
  error.value = "";
  try { const result = await request<{ data: NodeQuality[] }>(`/v1/admin/network/quality?${query({ client_network: network.value.trim() })}`); quality.value = result.data; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
async function register(): Promise<void> {
  busy.value = true; error.value = ""; notice.value = ""; revealedKey.value = "";
  try { const result = await item<RegisteredNode>("/v1/admin/network/nodes", "POST", { code: code.value.trim(), label: label.value.trim(), public_host: publicHost.value.trim(), public_port: Number(publicPort.value), protocol: protocol.value }); revealedKey.value = result.agent_key; code.value = ""; label.value = ""; publicHost.value = ""; publicPort.value = ""; protocol.value = ""; notice.value = "Node registered as inactive. The agent key is shown once."; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function toggle(node: NodeEndpoint): Promise<void> {
  busy.value = true; error.value = "";
  try { await item<NodeEndpoint>(`/v1/admin/network/nodes/${node.id}/enabled`, "PATCH", { enabled: !node.is_enabled }); await load(); await loadQuality(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function copyKey(): Promise<void> { if (revealedKey.value) await navigator.clipboard.writeText(revealedKey.value); notice.value = "Agent key copied to clipboard."; }
onMounted(() => { void load(); });
const createOpen=ref(false),capabilitiesOpen=ref(false);
const capabilityNode=ref<NodeEndpoint|null>(null);
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">NETWORK CONTROL</p><h1>Nodes and connection quality</h1><p class="subtitle">Manage endpoints and review measurements from each source network.</p></div><button class="btn secondary" @click="load(); loadQuality()">Refresh</button><button v-if="auth.can('network','create')" class="btn" :disabled="busy" @click="createOpen=true">+ Register node</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div class="split"><div class="card"><div class="card-pad"><h2>Registered nodes</h2><div class="hint-box">Registration adds a node to inventory. Test its core, connectivity and accounting before enabling customer traffic.</div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Label</th><th>Protocol</th><th>Address</th><th>Status</th><th></th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td><strong>{{ row.label }}</strong><br /><small class="mono">{{ faDigits(row.code) }}</small></td><td>{{ protocolLabels[row.protocol] ?? row.protocol }}</td><td>{{ faDigits(row.public_host) }}:{{ faNumber(row.public_port) }}</td><td><span class="badge" :class="row.is_enabled ? 'success' : 'warning'">{{ row.is_enabled ? 'Enabled' : 'Inactive' }}</span></td><td><button v-if="auth.can('network','read')" class="btn small secondary" @click="capabilityNode=row;capabilitiesOpen=true">Capabilities</button> <RouterLink class="btn small secondary" :to="`/network/${row.id}/cores`">Cores</RouterLink> <RouterLink class="btn small secondary" :to="`/network/${row.id}/configurations`">Configurations</RouterLink> <button v-if="auth.can('network', 'update')" class="btn small secondary" :disabled="busy" @click="toggle(row)">{{ row.is_enabled ? 'Disable' : 'Enable' }}</button></td></tr></tbody></table><div v-if="!loading && !rows.length" class="empty">No nodes registered yet.</div><div v-if="loading" class="empty">Loading nodes…</div></div><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} endpoint</span><button :disabled="page >= pages" @click="page++; load()">›</button></div></div>
  <NodeCapabilitiesModal v-if="auth.can('network','read')" :open="capabilitiesOpen" :node="capabilityNode" @close="capabilitiesOpen=false" />
  <Modal v-if="auth.can('network', 'create')" v-model="createOpen" title="Register node" :busy="busy" wide><p v-if="error" class="message error" role="alert">{{error}}</p><form class="form-grid" @submit.prevent="register"><label class="field"><span>Unique code</span><input v-model="code" required pattern="[A-Za-z0-9_-]+" dir="ltr" /></label><label class="field"><span>Label</span><input v-model="label" required /></label><label class="field"><span>Public hostname or IP</span><input v-model="publicHost" required dir="ltr" /></label><NumField v-model="publicPort" label="Port" /><label class="field"><span>Default protocol</span><select v-model="protocol" required><option value="" disabled>Choose a protocol</option><option v-for="(title, value) in protocolLabels" :key="value" :value="value">{{ title }}</option></select></label><button class="btn" :disabled="busy || !code || !label || !publicHost || !Number(publicPort) || !protocol">Register node</button></form><div v-if="revealedKey" class="form-grid" style="margin-top:20px"><div class="hint-box">This key is shown once. Store it privately for this node agent.</div><label class="field"><span>Agent key</span><input :type="reveal ? 'text' : 'password'" :value="revealedKey" readonly dir="ltr" /></label><div class="inline-actions"><button class="btn secondary" @click="reveal = !reveal">{{ reveal ? 'Hide' : 'Show key' }}</button><button class="btn secondary" @click="copyKey">Copy key</button></div></div></Modal></div>
  <div class="card" style="margin-top:18px"><div class="card-pad"><h2>Connection measurements</h2><div class="toolbar"><label class="field"><span>Measurement source network</span><input v-model="network" placeholder="e.g. MCI mobile" /></label><button class="btn secondary" :disabled="network.trim().length < 2" @click="loadQuality">View measurements</button></div><div class="hint-box">Scores use recent samples from the selected network. Customer routing requires measurements from their own access network.</div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Node</th><th>Protocol</th><th>Samples</th><th>Success</th><th>Average latency</th><th>Score</th></tr></thead><tbody><tr v-for="row in quality" :key="row.node_id"><td>{{ row.label }}</td><td>{{ protocolLabels[row.protocol] ?? row.protocol }}</td><td class="tabular">{{ faNumber(row.sample_count) }}</td><td class="tabular">{{ faNumber(row.successful_count) }}</td><td class="tabular">{{ row.average_latency_ms === null ? '—' : `${faNumber(row.average_latency_ms)} ms` }}</td><td class="tabular"><span class="badge" :class="row.score === null ? 'warning' : 'success'">{{ row.score === null ? 'Insufficient data' : faNumber(row.score) }}</span></td></tr></tbody></table><div v-if="!quality.length" class="empty">Not enough measurements are available for this network.</div></div></div>
</template>
