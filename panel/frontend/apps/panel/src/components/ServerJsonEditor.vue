<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";
import { item, request, query, type Page, type ConfigurationDetail, type ConfigurationDraft, type ConfigurationDownload, type ServerJsonState, type ServerJsonRevision, type ServerJsonDocument } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faNumber, faDate } from "@papilio/ui";
import type { JsonEditorRequest, JsonEditorReply } from "../workers/configurationJson.worker";
const props = defineProps<{ configuration: ConfigurationDetail }>();
const emit = defineEmits<{ changed: [configuration: ConfigurationDraft]; busy: [value: boolean] }>();
const auth = useAuth();
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
    worker.onerror = () => { pending.forEach(task => task.reject(new Error("The editor is not ready."))); pending.clear(); worker?.terminate(); worker = null; };
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
  <section v-if="auth.can('network','manage')" class="form-grid" aria-label="Core server JSON">
    <button v-if="!opened" type="button" class="btn secondary" :disabled="busy" @click="open">Full server JSON and history</button>
    <template v-else>
      <h3>JSON Core · {{ state?.core_kind }} · revision {{ faNumber(state?.revision ?? configuration.revision) }}</h3>
      <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
      <p v-if="state && !state.supported">This core uses a native configuration file. Use the settings JSON editor or native download.</p>
      <template v-if="state?.supported">
        <p>Managed mode preserves authoritative customer inbounds while allowing DNS, routing and outbounds. Experimental mode allows a complete document but prevents customer assignment. Validate compatibility with the installed core before applying changes.</p>
        <p v-if="state.capacity">Document limit: {{ faNumber(state.capacity.max_document_bytes) }} bytes; depth: {{ faNumber(state.capacity.max_depth) }}.</p>
        <p v-if="!state.capacity?.enabled">New documents are disabled. You can restore automatic generation.</p>
        <label class="field">Document mode<select aria-label="Document mode" v-model="mode" :disabled="busy || !auth.can('network','update')" @change="dirty = true; preview = null"><option value="managed">Managed</option><option value="experimental">Experimental · no customer assignments</option></select></label>
        <label class="field">JSON Core<textarea v-model="text" class="json-input" dir="ltr" spellcheck="false" :disabled="busy" :readonly="!auth.can('network','update')" @input="dirty = true; preview = null" /></label>
        <label v-if="auth.can('network','update')" class="field">Change reason<input v-model="reason" minlength="3" maxlength="250" :disabled="busy" /></label>
        <div class="inline-actions">
          <button type="button" class="btn secondary" :disabled="busy" @click="format">Format document</button>
          <button v-if="auth.can('network','update')" type="button" class="btn" :disabled="busy || !dirty || reason.trim().length < 3 || !state.capacity?.enabled" @click="save()">Save server document</button>
          <button v-if="auth.can('network','update')" type="button" class="btn secondary" :disabled="busy || reason.trim().length < 3 || !state.document" @click="save(true)">Restore automatic generation</button>
          <button type="button" class="btn secondary" :disabled="busy" @click="fresh">{{ dirty ? 'Discard draft and reload current version' : 'Reload current version' }}</button>
          <button type="button" class="btn secondary" :disabled="busy || dirty" @click="showExport">Preview saved output</button>
        </div>
        <template v-if="preview"><p>The output contains private credentials. Keep it private.</p><pre class="json-input" dir="ltr">{{ preview.content }}</pre><button type="button" class="btn secondary" @click="download">Download core file</button></template>
        <h4>Server document history</h4>
        <p v-if="!history.length">No changes recorded yet.</p>
        <article v-for="row in history" :key="row.id"><p>Revision {{ faNumber(row.revision) }} · {{ faDate(row.created_at) }} · Staff {{ faNumber(row.staff_id) }} · {{ row.reason }}</p><p>{{ row.document?.mode === 'experimental' ? 'Experimental' : row.document ? 'Managed' : 'Automatic generation' }}</p><button v-if="auth.can('network','update')" type="button" class="btn secondary" :disabled="busy || dirty || reason.trim().length < 3" @click="save(false,row.id)">Restore this revision</button></article>
        <nav aria-label="History pages" class="inline-actions"><button type="button" class="btn secondary" :disabled="busy || page <= 1" @click="changePage(page-1)">Previous</button><span>{{ faNumber(page) }} of {{ faNumber(pages) }}</span><button type="button" class="btn secondary" :disabled="busy || page >= pages" @click="changePage(page+1)">Next</button></nav>
      </template>
    </template>
  </section>
</template>
<style scoped>
.json-input { min-height: 24rem; max-width: 100%; width: 100%; font-family: monospace; text-align: left; white-space: pre; overflow: auto; }
article { border-block-start: 1px solid var(--border); padding-block: .6rem; }
</style>
