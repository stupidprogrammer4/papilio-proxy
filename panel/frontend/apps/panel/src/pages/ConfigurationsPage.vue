<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { item, query, request, type ClientProfile, type ConfigurationDownload, type ConfigurationDetail, type ConfigurationDraft, type NodeEndpoint, type Page, type Subscription, type CoreInstance, type OpenVpnOptions } from "@papilio/api";
import Modal from "@papilio/ui/Modal.vue";
import { useAuth } from "@papilio/auth";
import OpenVpnEditor from "../components/OpenVpnEditor.vue";
import ServerJsonEditor from "../components/ServerJsonEditor.vue";
import ConfigurationJsonEditor from "../components/ConfigurationJsonEditor.vue";
import ConfigurationCorePicker from "../components/ConfigurationCorePicker.vue";
import ConfigurationHosts from "../components/ConfigurationHosts.vue";
import NumField from "@papilio/ui/NumField.vue";
import { faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";

const route = useRoute(); const auth = useAuth();
const { t } = useI18n();
const error = ref(""); const notice = ref(""); const busy = ref(false); const loading = ref(false);
const nodes = ref<NodeEndpoint[]>([]); const node = ref<NodeEndpoint | null>(null); const nodePage = ref(1); const nodePages = ref(1); const nodeQuery = ref("");
const editing = ref(false);
const openvpnValue=ref<OpenVpnOptions|null>(null),openvpnEditor=ref<InstanceType<typeof OpenVpnEditor>|null>(null);
const coreState = ref<"idle" | "loading" | "ready" | "error">("idle");
const protocol = ref(""); const listenPort = ref(""); const core = ref<CoreInstance | null>(null);
const protocolLabels: Record<string, string> = { vless_reality: "VLESS REALITY", vless_tls: "VLESS TLS", vmess_tls: "VMess TLS", trojan_tls: "Trojan TLS", shadowsocks: "Shadowsocks", hysteria2: "Hysteria 2", wireguard: "WireGuard", openvpn: "OpenVPN" };
const rows = ref<ConfigurationDraft[]>([]); const page = ref(1); const pages = ref(1); const selected = ref<ConfigurationDetail | null>(null);
const profilesState = ref<"idle" | "loading" | "ready" | "error">("idle");
const subscriptionsState = ref<"idle" | "loading" | "ready" | "error">("idle");
const choosingId = ref<number | null>(null);
const profiles = ref<ClientProfile[]>([]); const profilePage = ref(1); const profilePages = ref(1);
const subscriptions = ref<Subscription[]>([]); const subscriptionPage = ref(1); const subscriptionPages = ref(1); const subscription = ref<Subscription | null>(null);
const label = ref(""); const listen = ref(""); const serverName = ref(""); const targetPort = ref(""); const certificate = ref(""); const privateKey = ref(""); const transport = ref(""); const transportPath = ref("");
const serverAddress = ref(""); const clientSubnet = ref(""); const allowedIps = ref(""); const dns = ref(""); const clientAddress = ref("");
const statusLabels: Record<string, string> = { pending_provision: "Pending provisioning", active: "Active", expired: "Expired", failed: "Failed", cancelled: "Cancelled" };
const privateUrlSubscriptionId = ref<number | null>(null);
let listVersion = 0; let routeVersion = 0; let selectionVersion = 0;
const privateUrl = ref(""); const showUrl = ref(false); const rotateTarget = ref<number | null>(null);
const availableProtocols = computed(() => Object.fromEntries(Object.entries(protocolLabels).filter(([key]) => !core.value || core.value.supported_protocols.includes(key))));
const tls = computed(() => ["vless_tls", "vmess_tls", "trojan_tls", "hysteria2"].includes(protocol.value));
const hasTransport = computed(() => ["vless_tls", "vmess_tls", "trojan_tls"].includes(protocol.value));
const wireguard = computed(() => protocol.value === "wireguard");
const canManage = computed(() => auth.session?.scopes.some(s => ["*", "network:*", "network:manage"].includes(s)) ?? false);

function failed(cause: unknown): void { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
async function loadNodes(): Promise<void> {
  loading.value = true; error.value = "";
  try { const result = await request<Page<NodeEndpoint>>(`/v1/admin/network/nodes?${query({ page: nodePage.value, q: nodeQuery.value.trim() })}`); nodes.value = result.data; nodePages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { failed(cause); } finally { loading.value = false; }
}
async function load(): Promise<void> {
  const version = ++listVersion; loading.value = true; error.value = "";
  try { const result = await request<Page<ConfigurationDraft>>(`/v1/admin/network/configurations?${query({ page: page.value, node_id: node.value?.id, core_id: route.params.coreId ? Number(route.params.coreId) : undefined })}`); if(version !== listVersion) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if(version === listVersion) failed(cause); } finally { if(version === listVersion) loading.value = false; }
}
async function chooseNode(value: NodeEndpoint): Promise<void> { ++selectionVersion; configurationOpen.value = false; privateUrl.value = ""; privateUrlSubscriptionId.value = null; node.value = value; protocol.value = value.protocol; listenPort.value = String(value.public_port); core.value = null; page.value = 1; editing.value = false; selected.value = null; choosingId.value = null; label.value = ""; listen.value = ""; serverName.value = ""; certificate.value = ""; privateKey.value = ""; transport.value = ""; transportPath.value = ""; targetPort.value = ""; serverAddress.value = ""; clientSubnet.value = ""; allowedIps.value = ""; dns.value = ""; profiles.value = []; openvpnValue.value=null;await load(); }
const configurationOpen = ref(false);
function chooseCore(value: CoreInstance | null): void { core.value=value; if(value && !value.supported_protocols.includes(protocol.value)) protocol.value=value.supported_protocols.includes(node.value?.protocol??"") ? node.value?.protocol??"" : value.supported_protocols[0]??""; }
function beginCreate(): void {
  if (!node.value || busy.value) return;
  editing.value = false; selected.value = null; label.value = "";
  protocol.value = core.value ? (core.value.supported_protocols.includes(node.value.protocol) ? node.value.protocol : core.value.supported_protocols[0] ?? "") : node.value.protocol;
  listenPort.value = String(node.value.public_port); listen.value = "";
  serverName.value = ""; certificate.value = ""; privateKey.value = "";
  transport.value = ""; transportPath.value = ""; targetPort.value = "";
  serverAddress.value = ""; clientSubnet.value = ""; allowedIps.value = "";
  dns.value = ""; openvpnValue.value = null; profiles.value = [];
  error.value = ""; configurationOpen.value = true;
}
async function create(): Promise<void> {
  if (!node.value || (route.params.coreId && !core.value)) return; busy.value = true; error.value = ""; notice.value = "";
  const options: Record<string, unknown> = { protocol: protocol.value };
  if (!wireguard.value) options.listen_address = listen.value.trim();
  if (protocol.value === "vless_reality") Object.assign(options, { server_name: serverName.value.trim(), target_port: Number(targetPort.value) });
  if (tls.value) Object.assign(options, { server_name: serverName.value.trim(), certificate_path: certificate.value.trim(), private_key_path: privateKey.value.trim() });
  if (hasTransport.value) Object.assign(options, { transport: transport.value, transport_path: transport.value === "tcp" ? null : transportPath.value });
  if (wireguard.value) Object.assign(options, { server_address: serverAddress.value.trim(), client_subnet: clientSubnet.value.trim(), allowed_ips: allowedIps.value.split(",").map(s => s.trim()), dns: dns.value.split(",").map(s => s.trim()) });
  try { if(protocol.value === "openvpn"){if(!openvpnEditor.value)throw new Error("The OpenVPN form is not ready.");Object.assign(options,openvpnEditor.value.options(listen.value.trim()));} const path = editing.value && selected.value ? `/v1/admin/network/configurations/${selected.value.id}` : "/v1/admin/network/configurations"; const created = await item<ConfigurationDraft>(path, editing.value ? "PUT" : "POST", { expected_revision: editing.value ? selected.value?.revision : undefined, node_id: node.value.id, core_id: core.value?.id, listen_port: Number(listenPort.value), label: label.value.trim(), options }); notice.value = "Configuration draft saved. It has not been applied to the node."; await load(); configurationOpen.value = false; await chooseConfiguration(created.id); }
  catch (cause) { failed(cause); } finally { busy.value = false; }
}
async function loadProfiles(): Promise<void> {
  if (!selected.value) return;
  const configurationId = selected.value.id; const requestedPage = profilePage.value; profilesState.value = "loading";
  try { const result = await request<Page<ClientProfile>>(`/v1/admin/network/configurations/${configurationId}/profiles?${query({ page: requestedPage })}`); if (selected.value?.id !== configurationId || profilePage.value !== requestedPage) return; profiles.value = result.data; profilePages.value = result.meta.pager?.total_pages ?? 1; profilesState.value = "ready"; } catch (cause) { if (selected.value?.id === configurationId) { profilesState.value = "error"; failed(cause); } }
}
async function loadSubscriptions(): Promise<void> {
  subscriptionsState.value = "loading";
  try { const result = await request<Page<Subscription>>(`/v1/admin/subscriptions?${query({ page: subscriptionPage.value })}`); subscriptions.value = result.data; subscriptionPages.value = result.meta.pager?.total_pages ?? 1; subscriptionsState.value = "ready"; } catch (cause) { subscriptionsState.value = "error"; failed(cause); }
}
async function chooseConfiguration(configurationId: number): Promise<void> {
  const version = ++selectionVersion; error.value = ""; choosingId.value = configurationId;
  try {
    const detail = await item<ConfigurationDetail>(`/v1/admin/network/configurations/${configurationId}`);
    if (version !== selectionVersion) return;
    if (route.params.nodeId && detail.node_id !== Number(route.params.nodeId)) throw new Error("This configuration belongs to a different node.");
    if (route.params.coreId && detail.core_id !== Number(route.params.coreId)) throw new Error("This configuration belongs to a different core.");
    const [parentNode, parentCore] = await Promise.all([item<NodeEndpoint>(`/v1/admin/network/nodes/${detail.node_id}`), item<CoreInstance>(`/v1/admin/network/cores/${detail.core_id}`)]);
    if (version !== selectionVersion) return;
    node.value = parentNode; protocol.value = detail.protocol; listenPort.value = String(detail.listen_port); core.value = parentCore; profiles.value = []; profilesState.value = "loading";
    selected.value = detail; editing.value = true; profilePage.value = 1; subscription.value = null; privateUrl.value = ""; privateUrlSubscriptionId.value = null; rotateTarget.value = null;
    label.value = detail.label; const options = detail.options; openvpnValue.value=options.protocol==="openvpn"?options:null; listen.value = "listen_address" in options ? options.listen_address : "";
    serverName.value = "server_name" in options ? options.server_name : "";
    targetPort.value = options.protocol === "vless_reality" ? String(options.target_port) : "";
    certificate.value = "certificate_path" in options ? options.certificate_path : "";
    privateKey.value = "private_key_path" in options ? options.private_key_path : "";
    transport.value = "transport" in options ? options.transport : "";
    transportPath.value = "transport_path" in options ? options.transport_path ?? "" : "";
    serverAddress.value = options.protocol === "wireguard" ? options.server_address : "";
    clientSubnet.value = options.protocol === "wireguard" ? options.client_subnet : "";
    allowedIps.value = options.protocol === "wireguard" ? options.allowed_ips.join(", ") : "";
    dns.value = options.protocol === "wireguard" ? options.dns.join(", ") : "";
    await loadProfiles(); if (version === selectionVersion && auth.can("subscriptions")) await loadSubscriptions();
  } catch (cause) { if(version === selectionVersion) failed(cause); }
}
async function assign(): Promise<void> {
  if (!selected.value || !subscription.value) return; busy.value = true; error.value = "";
  try { await item<ClientProfile>(`/v1/admin/network/configurations/${selected.value.id}/profiles`, "POST", { subscription_id: subscription.value.id, client_address: selected.value.protocol === "wireguard" ? clientAddress.value.trim() : null }); notice.value = "Client profile created. The subscription becomes active after provisioning is acknowledged."; await loadProfiles(); }
  catch (cause) { failed(cause); } finally { busy.value = false; }
}
async function download(path: string): Promise<void> {
  busy.value = true; error.value = "";
  try { const file = await item<ConfigurationDownload>(path, "POST"); const url = URL.createObjectURL(new Blob([file.content], { type: file.media_type })); const anchor = document.createElement("a"); anchor.href = url; anchor.download = file.filename; anchor.click(); URL.revokeObjectURL(url); notice.value = "Private configuration downloaded."; }
  catch (cause) { failed(cause); } finally { busy.value = false; }
}
async function link(id: number, rotate: boolean): Promise<void> {
  busy.value = true; error.value = "";
  try { const result = await item<{ url: string }>(`/v1/admin/network/configurations/subscriptions/${id}/${rotate ? 'rotate-link' : 'link'}`, "POST"); privateUrl.value = result.url; privateUrlSubscriptionId.value = id; showUrl.value = false; rotateTarget.value = null; notice.value = rotate ? "Token rotated. The previous URL is no longer valid." : "Subscription URL ready. Public downloads require an active subscription."; }
  catch (cause) { failed(cause); } finally { busy.value = false; }
}
async function loadCore(): Promise<void> {
  if (!route.params.coreId || !node.value) return;
  const nodeId = node.value.id; const coreId = Number(route.params.coreId); const version = routeVersion;
  coreState.value = "loading"; error.value = "";
  try {
    const selectedCore = await item<CoreInstance>(`/v1/admin/network/cores/${coreId}`);
    if(version !== routeVersion || node.value?.id !== nodeId) return;
    if (selectedCore.node_id !== node.value.id) throw new Error("This core belongs to a different node.");
    core.value = selectedCore;
    protocol.value = selectedCore.supported_protocols.includes(node.value.protocol) ? node.value.protocol : selectedCore.supported_protocols[0] ?? "";
    coreState.value = "ready";
  } catch (cause) { if(version === routeVersion) { coreState.value = "error"; failed(cause); } }
}
watch(() => [route.params.nodeId, route.params.coreId, route.query.configuration_id], async () => {
  const version = ++routeVersion; ++selectionVersion; ++listVersion;
  configurationOpen.value = false; selected.value = null; choosingId.value = null;
  node.value = null; core.value = null; rows.value = []; profiles.value = [];
  privateUrl.value = ""; privateUrlSubscriptionId.value = null; rotateTarget.value = null;
  error.value = ""; notice.value = ""; page.value = 1;
  const nodeId = Number(route.params.nodeId);
  const configurationId = Number(route.query.configuration_id);
  try {
    if (route.params.nodeId) {
      const parent = await item<NodeEndpoint>(`/v1/admin/network/nodes/${nodeId}`);
      if(version !== routeVersion) return;
      await chooseNode(parent);
      if(version !== routeVersion) return;
      if (route.params.coreId) { await loadCore(); if(version !== routeVersion || coreState.value !== "ready") return; }
    } else { await loadNodes(); if(version !== routeVersion) return; await load(); }
    if(version !== routeVersion) return;
    if (Number.isSafeInteger(configurationId) && configurationId > 0) await chooseConfiguration(configurationId);
  } catch (cause) { if(version === routeVersion) failed(cause); }
}, {immediate: true});
onBeforeUnmount(() => { ++routeVersion; ++selectionVersion; ++listVersion; privateUrl.value = ""; });

</script>
<template>
  <div class="page-head"><div><p class="eyebrow">{{ t('configurations.eyebrow') }}</p><h1>{{ t('configurations.title') }}</h1><p class="subtitle">{{ node ? t('configurations.nodeSubtitle', { node: node.label, protocol }) : t('configurations.description') }}</p></div><div class="inline-actions"><button class="btn secondary" :disabled="loading" @click="load">{{ t('configurations.refresh') }}</button><button v-if="node && auth.can('network', 'create')" class="btn" :disabled="busy || (Boolean(route.params.coreId) && !core)" @click="beginCreate">{{ t('configurations.create') }}</button></div></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div class="hint-box">{{ t("configurations.draftNotice") }}</div>
  <section v-if="!route.params.nodeId" class="card card-pad" style="margin-top:18px"><h2>{{ t("configurations.selectNode") }}</h2><form class="toolbar" @submit.prevent="nodePage = 1; loadNodes()"><label class="field"><span>{{ t("configurations.searchNode") }}</span><input v-model="nodeQuery" /></label><button class="btn secondary">{{ t("configurations.search") }}</button></form><div class="inline-actions"><button v-for="candidate in nodes" :key="candidate.id" class="btn small secondary" :aria-pressed="node?.id === candidate.id" @click="chooseNode(candidate)">{{ candidate.label }}</button></div><p v-if="node">{{ t("configurations.selectedNode", { node: node.label }) }}</p><div class="pager"><button :disabled="nodePage <= 1" @click="nodePage--; loadNodes()">‹</button><span>{{ faNumber(nodePage) }}</span><button :disabled="nodePage >= nodePages" @click="nodePage++; loadNodes()">›</button></div></section>
  <div style="margin-top:18px"><section class="card"><div class="card-pad"><h2>{{ t("configurations.drafts") }}</h2></div><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t("configurations.label") }}</th><th>{{ t("configurations.node") }}</th><th>{{ t("configurations.protocol") }}</th><th>{{ t("configurations.status") }}</th><th></th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.label }}</td><td>{{ faNumber(row.node_id) }}</td><td>{{ row.protocol }} · {{ faNumber(row.listen_port) }}</td><td><span class="badge warning">{{ t("configurations.draft") }}</span></td><td><button class="btn small secondary" :disabled="busy" @click="chooseConfiguration(row.id)">{{ t("configurations.manage") }}</button></td></tr></tbody></table><div v-if="loading" class="empty">{{ t("configurations.loading") }}</div><div v-else-if="!rows.length" class="empty">{{ t("configurations.noConfigurations") }}</div></div><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages" @click="page++; load()">›</button></div></section>
  <Modal v-if="node && (!route.params.coreId || core) && auth.can('network', editing ? 'update' : 'create')" v-model="configurationOpen" :title="editing ? t('configurations.edit') : t('configurations.createTitle')" :busy="busy" wide><p v-if="error" class="message error" role="alert">{{ error }}</p><p class="subtitle">{{ t("configurations.nodeLabel", { node: node.label }) }}</p><p v-if="core">{{ t("configurations.selectedCore", { core: core.label, kind: core.kind }) }}</p><form class="form-grid" @submit.prevent="create"><ConfigurationCorePicker v-if="!editing && !route.params.coreId" :node-id="node.id" :model-value="core" @update:model-value="chooseCore" /><label class="field"><span>{{ t("configurations.protocol") }}</span><select v-model="protocol" :disabled="editing" required><option v-for="(name, key) in availableProtocols" :key="key" :value="key">{{ name }}</option></select></label><NumField v-if="!editing" v-model="listenPort" :label="t('configurations.listenPort')" /><p v-else>{{ t("configurations.listenPort") }}: {{ faNumber(selected?.listen_port ?? 0) }}</p><label class="field"><span>{{ t("configurations.label") }}</span><input v-model="label" required minlength="2" maxlength="100" /></label><label v-if="!wireguard" class="field"><span>{{ t("configurations.nodeListenAddress") }}</span><input v-model="listen" required dir="ltr" /></label><label v-if="tls || protocol === 'vless_reality'" class="field"><span>{{ t("configurations.serverName") }}</span><input v-model="serverName" required dir="ltr" /></label><NumField v-if="protocol === 'vless_reality'" v-model="targetPort" :label="t('configurations.realityPort')" /><template v-if="tls"><label class="field"><span>{{ t("configurations.certificatePath") }}</span><input v-model="certificate" required dir="ltr" /></label><label class="field"><span>{{ t("configurations.privateKeyPath") }}</span><input v-model="privateKey" required dir="ltr" /></label></template><template v-if="hasTransport"><label class="field"><span>{{ t("configurations.transport") }}</span><select v-model="transport" required><option disabled value="">{{ t("configurations.chooseTransport") }}</option><option value="tcp">TCP</option><option value="ws">WebSocket</option><option value="grpc">gRPC</option></select></label><label v-if="transport && transport !== 'tcp'" class="field"><span>{{ t(transport === 'ws' ? 'configurations.websocketPath' : 'configurations.grpcServiceName') }}</span><input v-model="transportPath" required dir="ltr" /></label></template><template v-if="wireguard"><label class="field"><span>{{ t("configurations.serverAddress") }}</span><input v-model="serverAddress" required dir="ltr" /></label><label class="field"><span>{{ t("configurations.clientRange") }}</span><input v-model="clientSubnet" required dir="ltr" /></label><label class="field"><span>{{ t("configurations.allowedRoutes") }}</span><input v-model="allowedIps" required dir="ltr" /></label><label class="field"><span>{{ t("configurations.dnsAddresses") }}</span><input v-model="dns" required dir="ltr" /></label></template><OpenVpnEditor v-if="protocol==='openvpn'" :key="selected?.id??node.id" ref="openvpnEditor" :value="openvpnValue" :disabled="busy" :editing="editing"/><button class="btn" :disabled="busy">{{ editing ? t("configurations.saveChanges") : t("configurations.createDraft") }}</button></form></Modal></div>
  <p v-if="route.params.coreId && coreState === 'loading'">{{ t("configurations.loadingCore") }}</p>
  <button v-if="route.params.coreId && coreState === 'error'" class="btn secondary" @click="loadCore">{{ t("configurations.retryCore") }}</button>
  <section v-if="selected" class="card card-pad" style="margin-top:18px"><div class="page-head"><h2>{{ selected.label }}</h2><button v-if="auth.can('network', 'update')" class="btn secondary" :disabled="busy" @click="editing=true;configurationOpen=true">{{ t("configurations.editSettings") }}</button></div><ServerJsonEditor :key="`server-${selected.id}`" :configuration="selected" @changed="chooseConfiguration($event.id)" @busy="busy = $event" /><ConfigurationJsonEditor :key="selected.id" :configuration="selected" @changed="chooseConfiguration($event.id)" @busy="busy = $event" /><ConfigurationHosts :key="selected.id" :configuration="selected" /><button v-if="canManage" class="btn secondary" :disabled="busy" @click="download(`/v1/admin/network/configurations/${selected.id}/server-download`)">{{ t("configurations.downloadServer") }}</button><template v-if="auth.can('subscriptions')"><h3>{{ t("configurations.selectSubscription") }}</h3><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t("configurations.subscription") }}</th><th>{{ t("configurations.customer") }}</th><th>{{ t("configurations.status") }}</th><th></th></tr></thead><tbody><tr v-for="candidate in subscriptions" :key="candidate.id"><td>{{ faNumber(candidate.id) }}</td><td>{{ faNumber(candidate.customer_id) }}</td><td>{{ t(`configurations.subscriptionStatuses.${candidate.status}`) }}</td><td><button class="btn small secondary" :disabled="!['pending_provision', 'active'].includes(candidate.status)" @click="subscription = candidate">{{ subscription?.id === candidate.id ? t("configurations.selected") : t("configurations.select") }}</button></td></tr></tbody></table></div><div class="pager"><button :disabled="subscriptionPage <= 1" @click="subscriptionPage--; loadSubscriptions()">‹</button><span>{{ faNumber(subscriptionPage) }}</span><button :disabled="subscriptionPage >= subscriptionPages" @click="subscriptionPage++; loadSubscriptions()">›</button></div><form v-if="subscription" class="toolbar" @submit.prevent="assign"><span>Subscription Selected: {{ faNumber(subscription.id) }}</span><label v-if="selected.protocol === 'wireguard'" class="field"><span>Client address (single-host CIDR)</span><input v-model="clientAddress" required dir="ltr" /></label><button v-if="auth.can('subscriptions', 'update') && auth.can('network', 'create')" class="btn" :disabled="busy">Create client profile</button></form></template>
    <h3>{{ t("configurations.clientProfiles") }}</h3><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t("configurations.id") }}</th><th>{{ t("configurations.subscription") }}</th><th>{{ t("configurations.tunnelAddress") }}</th><th></th></tr></thead><tbody><tr v-for="profile in profiles" :key="profile.id"><td>{{ faNumber(profile.id) }}</td><td>{{ faNumber(profile.subscription_id) }}</td><td>{{ profile.client_address ?? '—' }}</td><td><div v-if="canManage" class="inline-actions"><button class="btn small secondary" :disabled="busy" @click="download(`/v1/admin/network/configurations/profiles/${profile.id}/client-download`)">{{ t("configurations.clientConfiguration") }}</button><button v-if="auth.can('subscriptions', 'update')" class="btn small secondary" :disabled="busy" @click="link(profile.subscription_id, false)">{{ t("configurations.subscriptionUrl") }}</button><button v-if="auth.can('subscriptions', 'update')" class="btn small secondary" :disabled="busy" @click="rotateTarget = profile.subscription_id">{{ t("configurations.rotateToken") }}</button></div><div v-if="rotateTarget === profile.subscription_id" class="inline-actions"><span>{{ t("configurations.invalidateUrl") }}</span><button class="btn small" @click="link(profile.subscription_id, true)">{{ t("configurations.rotateToken") }}</button><button class="btn small secondary" @click="rotateTarget = null">{{ t("configurations.cancel") }}</button></div></td></tr></tbody></table><div v-if="profilesState === 'loading'" class="empty">{{ t("configurations.loadingProfiles") }}</div><div v-else-if="profilesState === 'error'" class="message error">{{ t("configurations.profilesFailed") }}</div><div v-else-if="profilesState === 'ready' && !profiles.length" class="empty">{{ t("configurations.noProfiles") }}</div></div><div class="pager"><button :disabled="profilePage <= 1" @click="profilePage--; loadProfiles()">‹</button><span>{{ faNumber(profilePage) }}</span><button :disabled="profilePage >= profilePages" @click="profilePage++; loadProfiles()">›</button></div><div v-if="privateUrl" class="form-grid"><label class="field"><span>{{ t("configurations.privateUrl", { id: faNumber(privateUrlSubscriptionId ?? 0) }) }}</span><input :type="showUrl ? 'text' : 'password'" :value="privateUrl" readonly dir="ltr" /></label><button class="btn secondary" @click="showUrl = !showUrl">{{ showUrl ? t("configurations.hideUrl") : t("configurations.showUrl") }}</button></div>
  </section>
</template>
