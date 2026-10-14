<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";
import { item, request, query, type Page, type ConfigurationDetail, type ConfigurationDraft, type ConfigurationDownload, type ServerJsonState, type ServerJsonRevision, type ServerJsonDocument } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { useI18n } from "vue-i18n";
import { faNumber, faDate } from "@papilio/ui";
import type { JsonEditorRequest, JsonEditorReply } from "../workers/configurationJson.worker";
const props = defineProps<{ configuration: ConfigurationDetail }>();
const emit = defineEmits<{ changed: [configuration: ConfigurationDraft]; busy: [value: boolean] }>();
const auth = useAuth();
const { t } = useI18n();
const opened = ref(false), busy = ref(false), dirty = ref(false), error = ref(""), notice = ref("");
const state = ref<ServerJsonState | null>(null), text = ref(""), reason = ref(""), mode = ref<ServerJsonDocument["mode"]>("managed");
const history = ref<ServerJsonRevision[]>([]), page = ref(1), pages = ref(1), preview = ref<ConfigurationDownload | null>(null);
const base = `/v1/admin/network/configurations/${props.configuration.id}`;
const defaultSource = '{\n  "inbounds": [{"$papilio": "managed"}]\n}';
let alive = true, sequence = 0, worker: Worker | null = null;
const pending = new Map<number, { resolve: (reply: JsonEditorReply) => void; reject: (error: Error) => void }>();
function compute(text: string): Promise<JsonEditorReply> {
  if (!worker) {
    worker = new Worker(new URL("../workers/configurationJson.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = ({ data }: MessageEvent<JsonEditorReply>) => { const task = pending.get(data.id); pending.delete(data.id); task?.resolve(data); };
    worker.onerror = () => { pending.forEach(task => task.reject(new Error(t("configurationEditors.editorNotReady")))); pending.clear(); worker?.terminate(); worker = null; };
  }
  const id = ++sequence;
  const result = new Promise<JsonEditorReply>((resolve, reject) => pending.set(id, { resolve, reject }));
  const message: JsonEditorRequest = { id, action: "document", text };
  worker.postMessage(message); return result;
}
function lock(value: boolean): void { busy.value = value; emit("busy", value); }
function failed(cause: unknown): void { if (alive) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
async function historyPage(next: number): Promise<void> {
  const result = await request<Page<ServerJsonRevision>>(`${base}/server-json/history?${query({ page: next })}`);
  if (!alive) return; history.value = result.data; page.value = next; pages.value = result.meta.pager?.total_pages ?? 1;
}
async function fresh(): Promise<void> {
  lock(true); error.value = ""; notice.value = "";
  try {
    const current = await item<ServerJsonState>(`${base}/server-json`);
    if (!alive) return;
    state.value = current; text.value = current.document?.source ?? defaultSource; mode.value = current.document?.mode ?? "managed"; dirty.value = false; preview.value = null;
    await historyPage(1);
  } catch (cause) { failed(cause); } finally { if (alive) lock(false); }
}
async function open(): Promise<void> { opened.value = true; await fresh(); }
async function format(): Promise<void> {
  lock(true); error.value = "";
  try { const parsed = await compute(text.value); if (!parsed.success) throw new Error(parsed.message); if (alive) text.value = parsed.text ?? text.value; }
  catch (cause) { failed(cause); } finally { if (alive) lock(false); }
}
async function save(reset = false, revisionId?: number): Promise<void> {
  if (!state.value) return; lock(true); error.value = ""; notice.value = "";
  try {
    const source = text.value;
    if (!reset && revisionId === undefined) { const parsed = await compute(source); if (!parsed.success) throw new Error(parsed.message); }
    const path = revisionId === undefined ? `${base}/server-json` : `${base}/server-json/history/${revisionId}/restore`;
    const body = revisionId === undefined ? { expected_revision: state.value.revision, reason: reason.value, document: reset ? null : { mode: mode.value, source } } : { expected_revision: state.value.revision, reason: reason.value };
    const result = await item<ConfigurationDraft>(path, revisionId === undefined ? "PUT" : "POST", body);
    if (!alive) return;
    state.value.revision = result.revision; dirty.value = false; emit("changed", result);
    await fresh(); if (alive) { notice.value = "Revision saved. Node application requires provisioning."; reason.value = ""; }
  } catch (cause) { failed(cause); } finally { if (alive) lock(false); }
}
async function showExport(): Promise<void> {
  lock(true); error.value = "";
  try { const result = await item<ConfigurationDownload>(`${base}/server-download`, "POST", {}); if (alive) preview.value = result; }
  catch (cause) { failed(cause); } finally { if (alive) lock(false); }
}
function download(): void {
  if (!preview.value) return;
  const url = URL.createObjectURL(new Blob([preview.value.content], { type: preview.value.media_type }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = preview.value.filename; anchor.click(); URL.revokeObjectURL(url);
}
async function changePage(next: number): Promise<void> { lock(true); error.value = ""; try { await historyPage(next); } catch (cause) { failed(cause); } finally { if (alive) lock(false); } }
watch(() => props.configuration.revision, () => { if (!opened.value || busy.value || props.configuration.revision === state.value?.revision) return; if (dirty.value) { error.value = "The revision changed. Your draft is preserved; reload the current revision."; return; } void fresh(); });
onUnmounted(() => { alive = false; worker?.terminate(); pending.forEach(task => task.reject(new Error("Editor closed."))); pending.clear(); });
</script>
<template>
  <section v-if="auth.can('network','manage')" class="form-grid" :aria-label="t('configurationEditors.serverRegion')">
    <button v-if="!opened" type="button" class="btn secondary" :disabled="busy" @click="open">{{ t("configurationEditors.serverOpen") }}</button>
    <template v-else>
      <h3>{{ t("configurationEditors.serverTitle") }} · {{ state?.core_kind }} · {{ t("configurationEditors.revision", { revision: faNumber(state?.revision ?? configuration.revision) }) }}</h3>
      <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
      <p v-if="state && !state.supported">{{ t("configurationEditors.nativeCore") }}</p>
      <template v-if="state?.supported">
        <p>{{ t("configurationEditors.modeHint") }}</p>
        <p v-if="state.capacity">{{ t("configurationEditors.documentLimits", { bytes: faNumber(state.capacity.max_document_bytes), depth: faNumber(state.capacity.max_depth) }) }}</p>
        <p v-if="!state.capacity?.enabled">{{ t("configurationEditors.documentsDisabled") }}</p>
        <label class="field">{{ t("configurationEditors.documentMode") }}<select :aria-label="t('configurationEditors.documentMode')" v-model="mode" :disabled="busy || !auth.can('network','update')" @change="dirty = true; preview = null"><option value="managed">{{ t("configurationEditors.managedMode") }}</option><option value="experimental">{{ t("configurationEditors.experimentalNoAssignments") }}</option></select></label>
        <label class="field">{{ t("configurationEditors.jsonCore") }}<textarea v-model="text" class="json-input" dir="ltr" spellcheck="false" :disabled="busy" :readonly="!auth.can('network','update')" @input="dirty = true; preview = null" /></label>
        <label v-if="auth.can('network','update')" class="field">{{ t("configurationEditors.changeReason") }}<input v-model="reason" minlength="3" maxlength="250" :disabled="busy" /></label>
        <div class="inline-actions">
          <button type="button" class="btn secondary" :disabled="busy" @click="format">{{ t("configurationEditors.formatDocument") }}</button>
          <button v-if="auth.can('network','update')" type="button" class="btn" :disabled="busy || !dirty || reason.trim().length < 3 || !state.capacity?.enabled" @click="save()">{{ t("configurationEditors.saveServerDocument") }}</button>
          <button v-if="auth.can('network','update')" type="button" class="btn secondary" :disabled="busy || reason.trim().length < 3 || !state.document" @click="save(true)">{{ t("configurationEditors.restoreAutomatic") }}</button>
          <button type="button" class="btn secondary" :disabled="busy" @click="fresh">{{ dirty ? 'Discard draft and reload current version' : 'Reload current version' }}</button>
          <button type="button" class="btn secondary" :disabled="busy || dirty" @click="showExport">{{ t("configurationEditors.previewOutput") }}</button>
        </div>
        <template v-if="preview"><p>{{ t("configurationEditors.privateCredentials") }}</p><pre class="json-input" dir="ltr">{{ preview.content }}</pre><button type="button" class="btn secondary" @click="download">{{ t("configurationEditors.downloadCore") }}</button></template>
        <h4>{{ t("configurationEditors.serverHistory") }}</h4>
        <p v-if="!history.length">{{ t("configurationEditors.noHistory") }}</p>
        <article v-for="row in history" :key="row.id"><p>{{ t("configurationEditors.revision", { revision: faNumber(row.revision) }) }} · {{ faDate(row.created_at) }} · {{ t("configurationEditors.staff", { id: faNumber(row.staff_id) }) }} · {{ row.reason }}</p><p>{{ t(row.document?.mode === 'experimental' ? 'configurationEditors.experimental' : row.document ? 'configurationEditors.managed' : 'configurationEditors.automatic') }}</p><button v-if="auth.can('network','update')" type="button" class="btn secondary" :disabled="busy || dirty || reason.trim().length < 3" @click="save(false,row.id)">{{ t("configurationEditors.restoreRevision") }}</button></article>
        <nav :aria-label="t('configurationEditors.historyPages')" class="inline-actions"><button type="button" class="btn secondary" :disabled="busy || page <= 1" @click="changePage(page-1)">{{ t("configurationEditors.previous") }}</button><span>{{ t("configurationEditors.page", { page: faNumber(page), pages: faNumber(pages) }) }}</span><button type="button" class="btn secondary" :disabled="busy || page >= pages" @click="changePage(page+1)">{{ t("configurationEditors.next") }}</button></nav>
      </template>
    </template>
  </section>
</template>
<style scoped>
.json-input { min-height: 24rem; max-width: 100%; width: 100%; font-family: monospace; text-align: left; white-space: pre; overflow: auto; }
article { border-block-start: 1px solid var(--border); padding-block: .6rem; }
</style>
