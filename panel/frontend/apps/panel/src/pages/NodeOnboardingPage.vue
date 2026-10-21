<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onMounted, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, privateFile, query, type AgentRuntime, type CertificatePolicy, type ManagedNode, type ManagedNodePage, type NodeRegistration, type NodeOperation } from "@papilio/api";

const { t } = useI18n();
const rows = ref<ManagedNode[]>([]);
const selected = ref<ManagedNode | null>(null);
const operation = ref<NodeOperation | null>(null);
const name = ref("");
const endpoint = ref("");
const defaults = ref<{ runtime: AgentRuntime; certificate_policy: CertificatePolicy } | null>(null);
const search = ref("");
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
let requestKey = newRequestKey();
const numericFields = ["request_timeout_seconds", "read_header_timeout_seconds", "idle_timeout_seconds", "shutdown_timeout_seconds", "max_body_bytes", "max_grpc_reply_bytes"] as const;
const certificateFields = ["validity_seconds", "authority_validity_seconds", "backdate_seconds"] as const;
onBeforeUnmount(() => lifetime.abort());

async function loadRows(): Promise<void> {
  const result = await request<ManagedNodePage>(`/v1/nodes?${query({ q: search.value, page: page.value, page_size: pageSize.value })}`, "GET", undefined, { signal: lifetime.signal });
  rows.value = result.items;
  total.value = result.count;
}

async function readSelected(node: ManagedNode): Promise<void> {
  const current = await request<ManagedNode>(`/v1/nodes/${node.id}`, "GET", undefined, { signal: lifetime.signal });
  selected.value = current;
  operation.value = current.last_operation_id ? await request<NodeOperation>(`/v1/nodes/${current.id}/operations/${current.last_operation_id}`, "GET", undefined, { signal: lifetime.signal }) : null;
}

async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try { await action(); }
  catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("nodes.failed"); }
  finally { busy.value = false; }
}

async function refresh(): Promise<void> {
  await perform(async () => {
    await loadRows();
    if (selected.value) await readSelected(selected.value);
  });
}

async function select(node: ManagedNode): Promise<void> {
  await perform(async () => { await readSelected(node); });
}

async function create(): Promise<void> {
  if (!defaults.value) return;
  await perform(async () => {
    const result = await request<NodeRegistration>("/v1/nodes", "POST", { name: name.value, endpoint_url: endpoint.value, request_key: requestKey, ...defaults.value }, { signal: lifetime.signal });
    requestKey = newRequestKey();
    selected.value = result.node;
    operation.value = result.operation;
    name.value = "";
    endpoint.value = "";
    await loadRows();
  });
}

async function check(): Promise<void> {
  const node = selected.value;
  if (!node) return;
  await perform(async () => {
    operation.value = await request<NodeOperation>(`/v1/nodes/${node.id}/operations`, "POST", { kind: "check_connection", request_key: newRequestKey() }, { signal: lifetime.signal });
  });
}

async function download(): Promise<void> {
  const node = selected.value;
  if (!node) return;
  await perform(async () => {
    const blob = await privateFile(`/v1/nodes/${node.id}/bootstrap`, "POST", { signal: lifetime.signal });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `papilio-node-${node.id}.zip`;
    anchor.click();
    URL.revokeObjectURL(url);
  });
}

async function find(): Promise<void> { page.value = 1; await refresh(); }
async function turn(delta: number): Promise<void> { page.value += delta; await refresh(); }
onMounted(async () => {
  await perform(async () => {
    defaults.value = await request("/v1/nodes/defaults", "GET", undefined, { signal: lifetime.signal });
    await loadRows();
  });
});
</script>

<template>
  <div class="stack">
    <header class="page-heading"><h1>{{ t('nodes.title') }}</h1><p>{{ t('nodes.help') }}</p></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <button class="btn secondary" data-testid="node-refresh" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
    <section class="card card-pad">
      <h2>{{ t('nodes.create') }}</h2>
      <form v-if="defaults" class="form-grid" @submit.prevent="create">
        <fieldset class="form-grid" :disabled="busy">
          <label class="field"><span>{{ t('nodes.name') }}</span><input v-model="name" data-testid="node-name" required maxlength="80" /></label>
          <label class="field"><span>{{ t('nodes.endpoint') }}</span><input v-model="endpoint" data-testid="node-endpoint" type="url" dir="ltr" required maxlength="500" placeholder="https://node.example.com:9443" /></label>
          <details><summary data-testid="node-advanced">{{ t('nodes.advanced') }}</summary>
            <div class="form-grid">
              <p>{{ t('nodes.runtimeHelp') }}</p>
              <label v-for="field in (['listen_address', 'xray_api_address'] as const)" :key="field" class="field"><span>{{ t(`nodes.fields.${field}`) }}</span><input v-model="defaults.runtime[field]" dir="ltr" required /></label>
              <label v-for="field in numericFields" :key="field" class="field"><span>{{ t(`nodes.fields.${field}`) }}</span><input v-model.number="defaults.runtime[field]" :data-testid="`node-${field}`" type="number" min="1" :max="field === 'max_body_bytes' ? Number.MAX_SAFE_INTEGER : 2147483647" step="1" required /></label>
              <label v-for="field in certificateFields" :key="field" class="field"><span>{{ t(`nodes.fields.${field}`) }}</span><input v-model.number="defaults.certificate_policy[field]" type="number" :min="field === 'backdate_seconds' ? 0 : 1" max="2147483647" step="1" required /></label>
            </div>
          </details>
          <button class="btn" data-testid="node-create" type="submit">{{ t('nodes.create') }}</button>
        </fieldset>
      </form>
    </section>
    <section class="card card-pad form-grid">
      <form class="form-grid" @submit.prevent="find"><label class="field"><span>{{ t('nodes.search') }}</span><input v-model="search" data-testid="node-search" maxlength="200" :disabled="busy" /></label><button class="btn secondary" data-testid="node-search-submit" :disabled="busy">{{ t('nodes.search') }}</button></form>
      <p>{{ t('nodes.total', { count: total }) }}</p>
      <div class="table-wrap" data-testid="node-list"><table class="data-table"><thead><tr><th>{{ t('nodes.name') }}</th><th>{{ t('nodes.endpoint') }}</th><th>{{ t('nodes.connection') }}</th></tr></thead><tbody>
        <tr v-for="node in rows" :key="node.id"><td><button class="btn secondary" data-testid="node-row" :disabled="busy" @click="select(node)">{{ node.name }}</button></td><td dir="ltr">{{ node.endpoint_url }}</td><td>{{ t(node.last_reachable === null ? 'nodes.unchecked' : node.last_reachable ? 'nodes.reachable' : 'nodes.unreachable') }}</td></tr>
      </tbody></table></div>
      <div class="pager"><button :disabled="busy || page <= 1" @click="turn(-1)">‹</button><span>{{ page }}</span><button :disabled="busy || page * pageSize >= total" @click="turn(1)">›</button></div>
    </section>
    <section v-if="selected" class="card card-pad form-grid" data-testid="node-detail">
      <h2>{{ selected.name }}</h2><p dir="ltr">{{ selected.endpoint_url }}</p>
      <p>{{ t(selected.credentials_ready ? 'nodes.credentialsReady' : 'nodes.credentialsPending') }}</p>
      <p>{{ t('nodes.expires') }}: {{ selected.certificate_expires_at ? new Date(selected.certificate_expires_at).toLocaleString() : '—' }}</p>
      <p>{{ t('nodes.connection') }}: {{ t(selected.last_reachable === null ? 'nodes.unchecked' : selected.last_reachable ? 'nodes.reachable' : 'nodes.unreachable') }}</p>
      <p v-if="selected.last_checked_at">{{ t('foundation.observed') }}: {{ new Date(selected.last_checked_at).toLocaleString() }}</p>
      <p v-if="operation" aria-live="polite">{{ t(`nodes.kinds.${operation.kind}`) }} · {{ t(`foundation.states.${operation.status}`) }} <span v-if="operation.error_code">({{ t(`nodes.errors.${operation.error_code}`) }})</span></p>
      <p>{{ t('nodes.bootstrapHelp') }}</p>
      <button class="btn" data-testid="node-bootstrap" :disabled="busy || !selected.credentials_ready" @click="download">{{ t('nodes.download') }}</button>
      <button class="btn secondary" :disabled="busy || !selected.credentials_ready" @click="check">{{ t('nodes.check') }}</button>
      <p class="hint-box">{{ t('nodes.limits') }}</p>
    </section>
  </div>
</template>
