<script setup lang="ts">
import { ref, watch, onUnmounted } from "vue";
import Modal from "@papilio/ui/Modal.vue";
import { item, type CoreInstance, type CoreExport } from "@papilio/api";
const props = defineProps<{ core: CoreInstance | null }>();
const emit = defineEmits<{ close: [] }>();
const mode = ref<CoreExport["mode"]>("isolated"), busy = ref(false), error = ref("");
const result = ref<CoreExport | null>(null);
let sequence = 0;
watch(() => props.core?.id, () => { ++sequence; result.value = null; error.value = ""; busy.value = false; mode.value = "isolated"; });
watch(mode, () => { ++sequence; result.value = null; error.value = ""; busy.value = false; });
onUnmounted(() => { ++sequence; result.value = null; });
async function generate(): Promise<void> {
  const core = props.core; if (!core) return;
  const current = ++sequence; busy.value = true; error.value = ""; result.value = null;
  try {
    const exported = await item<CoreExport>(`/v1/admin/network/cores/${core.id}/export`, "POST", { mode: mode.value });
    if (current === sequence && props.core?.id === core.id) result.value = exported;
  } catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : "Could not export the core."; }
  finally { if (current === sequence) busy.value = false; }
}
function download(index: number): void {
  const artifact = result.value?.artifacts[index]; if (!artifact) return;
  const url = URL.createObjectURL(new Blob([artifact.content], {type: artifact.media_type}));
  const link = document.createElement("a"); link.href = url; link.download = artifact.filename; link.click(); URL.revokeObjectURL(url);
}
</script>
<template>
  <Modal :model-value="core !== null" :title="`Export ${core?.label ?? 'core'}`" :busy="busy" wide @update:model-value="value => { if (!value) emit('close'); }">
    <p>Build an export from every configuration assigned to this core. This does not apply or start a core.</p>
    <form class="form-grid" @submit.prevent="generate">
      <label class="field"><span>Output mode</span><select v-model="mode" :disabled="busy"><option value="isolated">Independent configuration files · all core types</option><option v-if="core?.kind === 'xray' || core?.kind === 'sing_box'" value="merged">One combined server JSON · matching shared settings required</option></select></label>
      <button class="btn" :disabled="busy">{{busy ? 'Generating…' : 'Generate export'}}</button>
    </form>
    <p v-if="error" class="message error" role="alert">{{error}}</p>
    <section v-if="result" class="form-grid">
      <p class="hint-box">Not applied. Files include server secrets; keep downloaded files private.</p>
      <article v-for="(artifact, index) in result.artifacts" :key="artifact.filename" class="card card-pad">
        <h3>{{artifact.filename}}</h3>
        <p>Configurations: {{artifact.configurations.map(row => `#${row.configuration_id} · revision ${row.revision}`).join(', ')}}</p>
        <label class="field"><span>SHA-256</span><input :value="artifact.sha256" readonly /></label>
        <details><summary>Preview server configuration</summary><label class="field"><textarea :value="artifact.content" readonly rows="12" spellcheck="false" /></label></details>
        <button type="button" class="btn secondary" @click="download(index)">Download file</button>
      </article>
    </section>
  </Modal>
</template>
