<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from "vue";
import Modal from "@papilio/ui/Modal.vue";
import { ApiError, item, request, query, type CoreInstance, type CoreRuntimeState, type CoreRuntimeRevision, type CoreRuntimeCommand, type RuntimeAction, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faDate } from "@papilio/ui";
const props = defineProps<{ core: CoreInstance | null }>();
const emit = defineEmits<{ close: [] }>();
const auth = useAuth();
const state = ref<CoreRuntimeState | null>(null), revisions = ref<CoreRuntimeRevision[]>([]), commands = ref<CoreRuntimeCommand[]>([]);
const revisionPage = ref(1), revisionPages = ref(1), commandPage = ref(1), commandPages = ref(1);
const readState = ref<"loading" | "ready" | "error">("loading"), busy = ref(false), error = ref(""), notice = ref("");
const mode = ref<CoreRuntimeRevision["mode"]>("isolated"), action = ref<RuntimeAction>("validate"), selected = ref<CoreRuntimeRevision | null>(null), reason = ref("");
const reconcileMode = ref<"observe" | "restore">("observe");
const expectedRevision = ref<number | null>(null), requestKey = ref(crypto.randomUUID());
const actionLabels: Record<RuntimeAction, string> = { validate: "Validate", apply: "Apply", restart: "Restart", stop: "Stop", rollback: "Rollback", reconcile: "Reconcile" };
const usageModeLabels = { disabled: "Disabled", observe: "Observe counters", polled_stop: "Poll counters and stop" };
const actions = computed(() => state.value?.allowed_actions ?? []);
const startBlocked = computed(() => Boolean(state.value?.start_blocked_reason));
const needsRevision = computed(() => ["validate", "apply", "rollback"].includes(action.value) || action.value === "reconcile" && reconcileMode.value === "restore");
const stale = computed(() => state.value !== null && expectedRevision.value !== null && state.value.revision !== expectedRevision.value);
const canWrite = computed(() => auth.can("network", "create") && auth.can("network", "manage"));
let sequence = 0;
function base(core: CoreInstance): string { return `/v1/admin/network/cores/${core.id}/runtime`; }
function message(cause: unknown): string { return cause instanceof Error ? cause.message : "Could not complete the runtime operation."; }
function newRequest(): void { requestKey.value = crypto.randomUUID(); notice.value = ""; }
watch([action, reconcileMode, selected, reason], newRequest);
async function refresh(): Promise<void> {
  const core = props.core; if (!core) return;
  const current = ++sequence; busy.value = true; error.value = ""; readState.value = "loading";
  try {
    const [runtime, versions, history] = await Promise.all([
      item<CoreRuntimeState>(base(core)),
      request<Page<CoreRuntimeRevision>>(`${base(core)}/revisions?${query({ page: revisionPage.value })}`),
      request<Page<CoreRuntimeCommand>>(`${base(core)}/commands?${query({ page: commandPage.value })}`),
    ]);
    if (current !== sequence) return;
    state.value = runtime; revisions.value = versions.data; commands.value = history.data;
    revisionPages.value = versions.meta.pager?.total_pages ?? 1; commandPages.value = history.meta.pager?.total_pages ?? 1;
    if (expectedRevision.value === null) expectedRevision.value = runtime.revision;
    readState.value = "ready";
  } catch (cause) { if (current === sequence) { readState.value = "error"; error.value = message(cause); } }
  finally { if (current === sequence) busy.value = false; }
}
function useCurrent(): void { expectedRevision.value = state.value?.revision ?? null; newRequest(); }
async function capture(): Promise<void> {
  const core = props.core; if (!core || expectedRevision.value === null) return;
  const current = sequence; busy.value = true; error.value = ""; notice.value = "";
  try {
    const revision = await item<CoreRuntimeRevision>(`${base(core)}/revisions`, "POST", { expected_revision: expectedRevision.value, mode: mode.value });
    if (current !== sequence) return;
    selected.value = revision; expectedRevision.value = null; revisionPage.value = 1;
    await refresh(); notice.value = "Immutable revision captured. No core was started.";
  } catch (cause) {
    if (current !== sequence) return;
    const detail = message(cause);
    if (cause instanceof ApiError && cause.status === 409) await refresh();
    error.value = detail;
  } finally { if (current === sequence || props.core?.id === core.id) busy.value = false; }
}
async function queue(): Promise<void> {
  const core = props.core; if (!core || expectedRevision.value === null) return;
  const current = sequence; busy.value = true; error.value = ""; notice.value = "";
  try {
    const command = await item<CoreRuntimeCommand>(`${base(core)}/commands`, "POST", {
      expected_revision: expectedRevision.value, action: action.value,
      revision_id: needsRevision.value ? selected.value?.id ?? null : null,
      reconcile_mode: action.value === "reconcile" ? reconcileMode.value : null,
      request_key: requestKey.value, reason: reason.value,
    });
    if (current !== sequence) return;
    expectedRevision.value = null; commandPage.value = 1;
    await refresh(); newRequest(); notice.value = `Command #${command.id} recorded (${command.state}). Refresh to see the node result.`;
  } catch (cause) {
    if (current !== sequence) return;
    const detail = message(cause);
    if (cause instanceof ApiError && cause.status === 409) await refresh();
    error.value = detail;
  } finally { if (current === sequence || props.core?.id === core.id) busy.value = false; }
}
watch(() => props.core?.id, () => {
  ++sequence; state.value = null; revisions.value = []; commands.value = []; selected.value = null;
  revisionPage.value = commandPage.value = revisionPages.value = commandPages.value = 1;
  reason.value = ""; mode.value = "isolated"; action.value = "validate"; reconcileMode.value = "observe"; expectedRevision.value = null;
  error.value = notice.value = ""; busy.value = false; newRequest();
  if (props.core) void refresh();
});
onUnmounted(() => { ++sequence; });
</script>
<template>
  <Modal :model-value="core !== null" :title="`Runtime · ${core?.label ?? 'core'}`" :busy="busy" wide @update:model-value="value => { if (!value) emit('close'); }">
    <p>Node #{{ core?.node_id }} · core #{{ core?.id }}. Saved revisions and queued commands remain separate from confirmed node execution.</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message" role="status">{{ notice }}</p>
    <div class="inline-actions"><button type="button" class="btn secondary" :disabled="busy" @click="refresh">Refresh runtime and history</button><span v-if="busy">Loading…</span></div>
    <template v-if="state && readState === 'ready'">
      <section class="card card-pad" aria-label="Runtime state">
        <p>Last reported status: <strong>{{state.observed_status}}</strong> · control revision {{state.revision}}</p>
        <p>Last observation: {{state.last_observed_at ? faDate(state.last_observed_at) : 'No acknowledged observation yet'}}. This is a command acknowledgement, not a live health check.</p>
        <p>Last reported process epoch: <code v-if="state.observed_process_epoch">{{state.observed_process_epoch}}</code><span v-else>Not reported</span></p>
        <p>Automatic core provisioning: <strong>{{state.automation_paused ? 'Paused for this core' : 'Not paused for this core'}}</strong></p>
        <p v-if="state.automation_paused" class="hint-box">An operator stop pauses automatic provisioning durably. An authorized Apply, Restart, Rollback or Restore command resumes automation.</p>
        <p>Desired: {{state.desired_revision_id ?? 'None'}} · applied: {{state.applied_revision_id ?? 'None'}} · validated: {{state.validated_revision_id ?? 'None'}}</p>
        <p v-if="!state.enabled" class="hint-box">Runtime control is disabled in application settings.</p>
        <p v-else-if="!state.allow_start" class="hint-box">Starting cores is disabled. Only the actions allowed by application settings are available.</p>
        <p v-if="state.start_blocked_reason" class="hint-box" role="status">Starting or replacing this core is currently blocked: <code>{{state.start_blocked_reason}}</code>. Capturing and validating a revision remain available when permitted.</p>
      </section>
      <section class="card card-pad" aria-label="Usage configuration capability">
        <h3>Usage configuration</h3>
        <template v-if="state.usage">
          <p>Configured mode: <strong>{{usageModeLabels[state.usage.mode]}}</strong></p>
          <p v-if="state.usage.mode === 'disabled'">Usage collection is disabled in application settings.</p>
          <p v-else>Configuration capability: <strong>{{state.usage.available ? 'Available' : 'Unavailable'}}</strong></p>
          <p v-if="state.usage.reason_code">Configuration reason: <code>{{state.usage.reason_code}}</code></p>
          <p>Configured local stats port: {{state.usage.configured_port ?? 'Not configured'}}</p>
          <p>Protected stats ports on this node: {{state.usage.protected_ports.length ? state.usage.protected_ports.join(', ') : 'None reported'}}</p>
          <p class="subtitle">These settings describe configuration support, not measured usage, installed enforcement or current connectivity.</p>
        </template>
        <p v-else>Usage configuration capability is unavailable right now.</p>
      </section>
      <section v-if="canWrite && state.enabled" class="form-grid" aria-label="Runtime operations">
        <p v-if="stale" class="hint-box">The control revision changed. Your draft is retained. Review the state, then use the current revision before retrying.</p>
        <button v-if="stale" type="button" class="btn secondary" :disabled="busy" @click="useCurrent">Use current control revision</button>
        <form class="form-grid" @submit.prevent="capture">
          <label class="field"><span>Snapshot output mode</span><select v-model="mode" :disabled="busy"><option value="isolated">Independent configuration files</option><option v-if="core?.kind === 'xray' || core?.kind === 'sing_box'" value="merged">Combined server JSON</option></select></label>
          <button class="btn secondary" :disabled="busy || stale">Capture immutable revision</button>
        </form>
        <form class="form-grid" @submit.prevent="queue">
          <label class="field"><span>Runtime action</span><select v-model="action" :disabled="busy"><option v-for="value in actions" :key="value" :value="value">{{actionLabels[value]}}</option></select></label>
          <template v-if="action === 'reconcile'">
            <label class="field"><span>Reconciliation mode</span><select v-model="reconcileMode" :disabled="busy"><option value="observe">Observe actual state</option><option value="restore" :disabled="!state.allow_start || startBlocked">Restore desired revision</option></select></label>
            <p v-if="reconcileMode === 'observe'">Observe records the node’s actual state without starting or changing core processes.</p>
            <p v-else>Restore validates and applies the selected desired revision. This can start core processes.</p>
          </template>
          <p v-if="action === 'stop'" class="hint-box">Queueing Stop pauses automatic core provisioning for this core. The node execution result is recorded separately.</p>
          <p v-else-if="action === 'apply' || action === 'restart' || action === 'rollback' || action === 'reconcile' && reconcileMode === 'restore'" class="hint-box">Queueing this operator command resumes automatic core provisioning for this core.</p>
          <p v-if="needsRevision">Selected revision: {{selected ? `#${selected.id} · ${selected.mode}` : 'Select a revision below'}}</p>
          <label class="field"><span>Command reason</span><input v-model="reason" required minlength="1" maxlength="250" :disabled="busy" /></label>
          <button class="btn" :disabled="busy || stale || !actions.includes(action) || (action === 'reconcile' && reconcileMode === 'restore' && (!state.allow_start || startBlocked)) || (needsRevision && !selected) || reason.trim().length < 1">Queue command</button>
        </form>
      </section>
      <section aria-label="Runtime revisions">
        <h3>Immutable revisions</h3><p v-if="!revisions.length">No revisions captured.</p>
        <article v-for="row in revisions" :key="row.id" class="card card-pad">
          <h4>Revision #{{row.id}} · {{row.mode}}</h4><p>{{row.artifact_count}} files · {{faDate(row.created_at)}} · {{row.created_by_staff_id === null ? 'System' : `Staff #${row.created_by_staff_id}`}}</p>
          <label class="field"><span>Bundle SHA-256</span><input :value="row.bundle_sha256" readonly /></label>
          <label v-if="row.membership_sha256" class="field"><span>Captured profile membership SHA-256</span><input :value="row.membership_sha256" readonly /></label>
          <p v-else>No captured profile provenance in this revision.</p>
          <p v-if="row.membership_sha256" class="subtitle">The digest identifies the captured membership manifest. It does not confirm installation, quota enforcement or current connectivity.</p>
          <label v-if="row.usage_sha256" class="field"><span>Captured usage configuration SHA-256</span><input :value="row.usage_sha256" readonly /></label>
          <p v-else>No captured usage configuration provenance in this revision.</p>
          <p v-if="row.usage_sha256" class="subtitle">This digest identifies the captured usage configuration. It does not prove collection, installation or quota enforcement.</p>
          <button v-if="canWrite && state.enabled" type="button" class="btn small secondary" :disabled="busy" :aria-pressed="selected?.id === row.id" @click="selected=row">{{selected?.id === row.id ? 'Selected revision' : 'Select revision'}}</button>
        </article>
        <nav aria-label="Revision pages" class="inline-actions"><button type="button" class="btn secondary" :disabled="busy || revisionPage <= 1" @click="revisionPage--; refresh()">Previous revisions</button><span>{{revisionPage}} of {{revisionPages}}</span><button type="button" class="btn secondary" :disabled="busy || revisionPage >= revisionPages" @click="revisionPage++; refresh()">Next revisions</button></nav>
      </section>
      <section aria-label="Runtime commands">
        <h3>Command history</h3><p v-if="!commands.length">No commands recorded.</p>
        <article v-for="row in commands" :key="row.id" class="card card-pad">
          <h4>Command #{{row.id}} · {{actionLabels[row.action]}}{{row.reconcile_mode ? ` (${row.reconcile_mode})` : ''}} · {{row.state}}</h4>
          <p>{{row.purpose === 'provisioning' ? 'Automatic provisioning' : 'Operator command'}}</p><p>Revision {{row.revision_id ?? 'None'}} · {{faDate(row.created_at)}} · {{row.created_by_staff_id === null ? 'System' : `Staff #${row.created_by_staff_id}`}}</p><p>{{row.reason}}</p>
          <p v-if="row.claim_until">Lease expires: {{faDate(row.claim_until)}}</p><p v-if="row.error_code" class="message error">Node error: {{row.error_code}}</p>
        </article>
        <nav aria-label="Command pages" class="inline-actions"><button type="button" class="btn secondary" :disabled="busy || commandPage <= 1" @click="commandPage--; refresh()">Previous commands</button><span>{{commandPage}} of {{commandPages}}</span><button type="button" class="btn secondary" :disabled="busy || commandPage >= commandPages" @click="commandPage++; refresh()">Next commands</button></nav>
      </section>
    </template>
  </Modal>
</template>
<style scoped>
section { margin-block: 1rem; }
article + article { margin-block-start: .75rem; }
input[readonly] { font-family: monospace; }
</style>
