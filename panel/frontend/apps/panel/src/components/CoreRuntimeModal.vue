<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from "vue";
import Modal from "@papilio/ui/Modal.vue";
import { ApiError, item, request, query, type CoreInstance, type CoreRuntimeState, type CoreRuntimeRevision, type CoreRuntimeCommand, type RuntimeAction, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faDate } from "@papilio/ui";
import {useI18n} from "vue-i18n";
const props = defineProps<{ core: CoreInstance | null }>();
const emit = defineEmits<{ close: [] }>();
const auth = useAuth();
const {t}=useI18n();
const state = ref<CoreRuntimeState | null>(null), revisions = ref<CoreRuntimeRevision[]>([]), commands = ref<CoreRuntimeCommand[]>([]);
const revisionPage = ref(1), revisionPages = ref(1), commandPage = ref(1), commandPages = ref(1);
const readState = ref<"loading" | "ready" | "error">("loading"), busy = ref(false), error = ref(""), notice = ref("");
const mode = ref<CoreRuntimeRevision["mode"]>("isolated"), action = ref<RuntimeAction>("validate"), selected = ref<CoreRuntimeRevision | null>(null), reason = ref("");
const reconcileMode = ref<"observe" | "restore">("observe");
const expectedRevision = ref<number | null>(null), requestKey = ref(crypto.randomUUID());
const actionLabels = computed<Record<RuntimeAction,string>>(() => ({ validate:t("network.runtime.validate"), apply:t("network.runtime.apply"), restart:t("network.runtime.restart"), stop:t("network.runtime.stop"), rollback:t("network.runtime.rollback"), reconcile:t("network.runtime.reconcile") }));
const usageModeLabels = computed(() => ({ disabled:t("settingsForm.disabled"), observe:t("network.runtime.observeCounters"), polled_stop:t("network.runtime.polledCounters") }));
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
    await refresh(); notice.value = t("network.runtime.captured");
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
    await refresh(); newRequest(); notice.value = t("network.runtime.commandRecorded",{id:command.id,state:command.state});
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
  <Modal :model-value="core !== null" :title="t('network.runtime.title',{label:core?.label ?? t('network.core')})" :busy="busy" wide @update:model-value="value => { if (!value) emit('close'); }">
    <p>{{t('network.runtime.identity',{node:core?.node_id,core:core?.id})}}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message" role="status">{{ notice }}</p>
    <div class="inline-actions"><button type="button" class="btn secondary" :disabled="busy" @click="refresh">{{t('network.runtime.refresh')}}</button><span v-if="busy">{{t('network.runtime.loading')}}</span></div>
    <template v-if="state && readState === 'ready'">
      <section class="card card-pad" :aria-label="t('network.runtime.state')">
        <p>{{t('network.runtime.status')}}: <strong>{{state.observed_status}}</strong> · {{t('network.runtime.controlRevision')}} {{state.revision}}</p>
        <p>{{t('network.runtime.lastObservation')}}: {{state.last_observed_at ? faDate(state.last_observed_at) : t('network.runtime.noObservation')}}. {{t('network.runtime.ack')}}</p>
        <p>{{t('network.runtime.epoch')}}: <code v-if="state.observed_process_epoch">{{state.observed_process_epoch}}</code><span v-else>{{t('network.runtime.notReported')}}</span></p>
        <p>{{t('network.runtime.automation')}}: <strong>{{state.automation_paused ? t('network.runtime.paused') : t('network.runtime.notPaused')}}</strong></p>
        <p v-if="state.automation_paused" class="hint-box">{{t('network.runtime.stopHint')}}</p>
        <p>{{t('network.runtime.desired')}}: {{state.desired_revision_id ?? t('network.runtime.none')}} · {{t('network.runtime.applied')}}: {{state.applied_revision_id ?? t('network.runtime.none')}} · {{t('network.runtime.validated')}}: {{state.validated_revision_id ?? t('network.runtime.none')}}</p>
        <p v-if="!state.enabled" class="hint-box">{{t('network.runtime.disabled')}}</p>
        <p v-else-if="!state.allow_start" class="hint-box">{{t('network.runtime.cannotStart')}}</p>
        <p v-if="state.start_blocked_reason" class="hint-box" role="status">{{t('network.runtime.blocked')}} <code>{{state.start_blocked_reason}}</code>. {{t('network.runtime.blockedHint')}}</p>
      </section>
      <section class="card card-pad" :aria-label="t('network.runtime.usageCapability')">
        <h3>{{t('network.runtime.usage')}}</h3>
        <template v-if="state.usage">
          <p>{{t('network.runtime.mode')}}: <strong>{{usageModeLabels[state.usage.mode]}}</strong></p>
          <p v-if="state.usage.mode === 'disabled'">{{t('network.runtime.disabledUsage')}}</p>
          <p v-else>{{t('network.runtime.capability')}}: <strong>{{state.usage.available ? t('network.runtime.available') : t('network.runtime.unavailable')}}</strong></p>
          <p v-if="state.usage.reason_code">{{t('network.runtime.reason')}}: <code>{{state.usage.reason_code}}</code></p>
          <p>{{t('network.runtime.port')}}: {{state.usage.configured_port ?? t('network.runtime.noneConfigured')}}</p>
          <p>{{t('network.runtime.protected')}}: {{state.usage.protected_ports.length ? state.usage.protected_ports.join(', ') : t('network.runtime.noneReported')}}</p>
          <p class="subtitle">{{t('network.runtime.scopeHint')}}</p>
        </template>
        <p v-else>{{t('network.runtime.usageUnavailable')}}</p>
      </section>
      <section v-if="canWrite && state.enabled" class="form-grid" :aria-label="t('network.runtime.operations')">
        <p v-if="stale" class="hint-box">{{t('network.runtime.stale')}}</p>
        <button v-if="stale" type="button" class="btn secondary" :disabled="busy" @click="useCurrent">{{t('network.runtime.useCurrent')}}</button>
        <form class="form-grid" @submit.prevent="capture">
          <label class="field"><span>{{t('network.runtime.snapshotMode')}}</span><select v-model="mode" :disabled="busy"><option value="isolated">{{t('network.runtime.isolated')}}</option><option v-if="core?.kind === 'xray' || core?.kind === 'sing_box'" value="merged">{{t('network.runtime.merged')}}</option></select></label>
          <button class="btn secondary" :disabled="busy || stale">{{t('network.runtime.capture')}}</button>
        </form>
        <form class="form-grid" @submit.prevent="queue">
          <label class="field"><span>{{t('network.runtime.action')}}</span><select v-model="action" :disabled="busy"><option v-for="value in actions" :key="value" :value="value">{{actionLabels[value]}}</option></select></label>
          <template v-if="action === 'reconcile'">
            <label class="field"><span>{{t('network.runtime.reconcileMode')}}</span><select v-model="reconcileMode" :disabled="busy"><option value="observe">{{t('network.runtime.observe')}}</option><option value="restore" :disabled="!state.allow_start || startBlocked">{{t('network.runtime.restore')}}</option></select></label>
            <p v-if="reconcileMode === 'observe'">{{t('network.runtime.observeHint')}}</p>
            <p v-else>{{t('network.runtime.restoreHint')}}</p>
          </template>
          <p v-if="action === 'stop'" class="hint-box">{{t('network.runtime.stopOperator')}}</p>
          <p v-else-if="action === 'apply' || action === 'restart' || action === 'rollback' || action === 'reconcile' && reconcileMode === 'restore'" class="hint-box">{{t('network.runtime.resumeOperator')}}</p>
          <p v-if="needsRevision">{{t('network.runtime.selectedRevision')}}: {{selected ? `#${selected.id} · ${selected.mode}` : t('network.runtime.selectBelow')}}</p>
          <label class="field"><span>{{t('network.runtime.reasonInput')}}</span><input v-model="reason" required minlength="1" maxlength="250" :disabled="busy" /></label>
          <button class="btn" :disabled="busy || stale || !actions.includes(action) || (action === 'reconcile' && reconcileMode === 'restore' && (!state.allow_start || startBlocked)) || (needsRevision && !selected) || reason.trim().length < 1">{{t('network.runtime.queue')}}</button>
        </form>
      </section>
      <section aria-label="Runtime revisions">
        <h3>{{t('network.runtime.revisions')}}</h3><p v-if="!revisions.length">{{t('network.runtime.noRevisions')}}</p>
        <article v-for="row in revisions" :key="row.id" class="card card-pad">
          <h4>{{t('settingsForm.revision')}} #{{row.id}} · {{row.mode}}</h4><p>{{row.artifact_count}} {{t('network.runtime.files')}} · {{faDate(row.created_at)}} · {{row.created_by_staff_id === null ? t('network.runtime.system') : `${t('network.runtime.staff')} #${row.created_by_staff_id}`}}</p>
          <label class="field"><span>{{t('network.runtime.bundleHash')}}</span><input :value="row.bundle_sha256" readonly /></label>
          <label v-if="row.membership_sha256" class="field"><span>{{t('network.runtime.membershipHash')}}</span><input :value="row.membership_sha256" readonly /></label>
          <p v-else>{{t('network.runtime.noMembership')}}</p>
          <p v-if="row.membership_sha256" class="subtitle">{{t('network.runtime.membershipHint')}}</p>
          <label v-if="row.usage_sha256" class="field"><span>{{t('network.runtime.usageHash')}}</span><input :value="row.usage_sha256" readonly /></label>
          <p v-else>{{t('network.runtime.noUsage')}}</p>
          <p v-if="row.usage_sha256" class="subtitle">{{t('network.runtime.usageHint')}}</p>
          <button v-if="canWrite && state.enabled" type="button" class="btn small secondary" :disabled="busy" :aria-pressed="selected?.id === row.id" @click="selected=row">{{selected?.id === row.id ? t('network.runtime.selected') : t('network.runtime.select')}}</button>
        </article>
        <nav :aria-label="t('network.runtime.revisionPages')" class="inline-actions"><button type="button" class="btn secondary" :disabled="busy || revisionPage <= 1" @click="revisionPage--; refresh()">{{t('network.runtime.previousRevisions')}}</button><span>{{t('automation.scheduleEditor.pages',{page:revisionPage,pages:revisionPages})}}</span><button type="button" class="btn secondary" :disabled="busy || revisionPage >= revisionPages" @click="revisionPage++; refresh()">{{t('network.runtime.nextRevisions')}}</button></nav>
      </section>
      <section :aria-label="t('network.runtime.commands')">
        <h3>{{t('network.runtime.commands')}}</h3><p v-if="!commands.length">{{t('network.runtime.noCommands')}}</p>
        <article v-for="row in commands" :key="row.id" class="card card-pad">
          <h4>Command #{{row.id}} · {{actionLabels[row.action]}}{{row.reconcile_mode ? ` (${row.reconcile_mode})` : ''}} · {{row.state}}</h4>
          <p>{{row.purpose === 'provisioning' ? t('network.runtime.automatic') : t('network.runtime.operatorCommand')}}</p><p>{{t('settingsForm.revision')}} {{row.revision_id ?? t('network.runtime.none')}} · {{faDate(row.created_at)}} · {{row.created_by_staff_id === null ? t('network.runtime.system') : `${t('network.runtime.staff')} #${row.created_by_staff_id}`}}</p><p>{{row.reason}}</p>
          <p v-if="row.claim_until">{{t('network.runtime.lease')}}: {{faDate(row.claim_until)}}</p><p v-if="row.error_code" class="message error">{{t('network.runtime.nodeError')}}: {{row.error_code}}</p>
        </article>
        <nav :aria-label="t('network.runtime.commandPages')" class="inline-actions"><button type="button" class="btn secondary" :disabled="busy || commandPage <= 1" @click="commandPage--; refresh()">{{t('network.runtime.previousCommands')}}</button><span>{{t('automation.scheduleEditor.pages',{page:commandPage,pages:commandPages})}}</span><button type="button" class="btn secondary" :disabled="busy || commandPage >= commandPages" @click="commandPage++; refresh()">{{t('network.runtime.nextCommands')}}</button></nav>
      </section>
    </template>
  </Modal>
</template>
<style scoped>
section { margin-block: 1rem; }
article + article { margin-block-start: .75rem; }
input[readonly] { font-family: monospace; }
</style>
