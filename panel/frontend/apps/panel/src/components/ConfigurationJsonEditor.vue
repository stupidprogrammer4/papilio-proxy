<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";
import { item, type ConfigurationDetail, type ConfigurationDraft } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { useI18n } from "vue-i18n";
import { faNumber } from "@papilio/ui";
import type { JsonEditorReply, JsonEditorRequest } from "../workers/configurationJson.worker";

const props = defineProps<{ configuration: ConfigurationDetail }>();
const emit = defineEmits<{ changed: [configuration: ConfigurationDraft]; busy: [busy: boolean] }>();
const auth = useAuth();
const { t } = useI18n();
const opened = ref(false), busy = ref(false), dirty = ref(false);
const text = ref(""), error = ref(""), notice = ref("");
const revision = ref(props.configuration.revision);
let alive = true, sequence = 0;
let worker: Worker | null = null;
const pending = new Map<number, { resolve: (reply: JsonEditorReply) => void; reject: (error: Error) => void }>();
function compute(request: Omit<JsonEditorRequest, "id">): Promise<JsonEditorReply> {
  if (!worker) {
    worker = new Worker(new URL("../workers/configurationJson.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = ({ data }: MessageEvent<JsonEditorReply>) => { const task = pending.get(data.id); pending.delete(data.id); task?.resolve(data); };
    worker.onerror = () => { pending.forEach(task => task.reject(new Error("The JSON editor is not ready. Please retry."))); pending.clear(); worker?.terminate(); worker = null; };
  }
  const id = ++sequence;
  const result = new Promise<JsonEditorReply>((resolve, reject) => pending.set(id, { resolve, reject }));
  worker.postMessage({ ...request, id });
  return result;
}
function state(value: boolean): void { busy.value = value; emit("busy", value); }
async function fresh(): Promise<void> {
  state(true); error.value = ""; notice.value = "";
  try {
    const current = await item<ConfigurationDetail>(`/v1/admin/network/configurations/${props.configuration.id}`);
    const result = await compute({ action: "print", value: { label: current.label, options: current.options } });
    if (!alive) return;
    if (!result.success) throw new Error(result.message);
    revision.value = current.revision; text.value = result.text ?? ""; dirty.value = false;
  } catch (cause) { if (alive) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (alive) state(false); }
}
async function open(): Promise<void> { opened.value = true; await fresh(); }
async function apply(save: boolean): Promise<void> {
  state(true); error.value = ""; notice.value = "";
  try {
    const parsed = await compute({ action: "parse", text: text.value, optionKeys: Object.keys(props.configuration.options) });
    if (!alive) return;
    if (!parsed.success || !parsed.value) throw new Error(parsed.message);
    if (!save) { text.value = parsed.text ?? text.value; return; }
    const updated = await item<ConfigurationDraft>(`/v1/admin/network/configurations/${props.configuration.id}`, "PUT", { ...parsed.value, expected_revision: revision.value });
    if (!alive) return;
    revision.value = updated.revision; dirty.value = false; text.value = parsed.text ?? text.value;
    notice.value = "JSON saved. The configuration revision has changed."; emit("changed", updated);
  } catch (cause) { if (alive) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (alive) state(false); }
}
watch(() => props.configuration.revision, () => {
  if (!opened.value || busy.value || props.configuration.revision === revision.value) return;
  if (dirty.value) { error.value = "The configuration changed. Your draft is preserved; reload the current revision before replacing it."; return; }
  void fresh();
});
onUnmounted(() => { alive = false; worker?.terminate(); pending.forEach(task => task.reject(new Error("Editor closed."))); pending.clear(); });
</script>
<template>
  <section class="form-grid" :aria-label="t('configurationEditors.settingsRegion')">
    <button v-if="!opened" type="button" class="btn secondary" :disabled="busy" @click="open">{{ t("configurationEditors.settingsOpen") }}</button>
    <template v-else>
      <h3>{{ t("configurationEditors.settingsTitle") }} · {{ t("configurationEditors.revision", { revision: faNumber(revision) }) }}</h3>
      <p>{{ t("configurationEditors.settingsHint") }}</p>
      <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
      <label class="field"><span>{{ t("configurationEditors.configurationJson") }}</span><textarea v-model="text" dir="ltr" spellcheck="false" class="json-input" :readonly="!auth.can('network', 'update')" :disabled="busy" @input="dirty = true" /></label>
      <div class="inline-actions">
        <button type="button" class="btn secondary" :disabled="busy || !text" @click="apply(false)">{{ t("configurationEditors.formatJson") }}</button>
        <button v-if="auth.can('network', 'update')" type="button" class="btn" :disabled="busy || !text || !dirty" @click="apply(true)">{{ t("configurationEditors.saveJson") }}</button>
        <button type="button" class="btn secondary" :disabled="busy" @click="fresh">{{ dirty ? t("configurationEditors.discardAndReload") : t("configurationEditors.reload") }}</button>
      </div>
    </template>
  </section>
</template>
<style scoped>
.json-input { min-height: 24rem; width: 100%; font-family: monospace; text-align: left; overflow-wrap: normal; white-space: pre; }
</style>
