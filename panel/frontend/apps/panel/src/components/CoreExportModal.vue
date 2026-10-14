<script setup lang="ts">
import { ref, watch, onUnmounted } from "vue";
import Modal from "@papilio/ui/Modal.vue";
import { item, type CoreInstance, type CoreExport } from "@papilio/api";
import {useI18n} from "vue-i18n";
const props = defineProps<{ core: CoreInstance | null }>();
const emit = defineEmits<{ close: [] }>();
const {t}=useI18n();
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
  <Modal :model-value="core !== null" :title="t('network.export.title',{label:core?.label ?? t('network.core')})" :busy="busy" wide @update:model-value="value => { if (!value) emit('close'); }">
    <p>{{t('network.export.description')}}</p>
    <form class="form-grid" @submit.prevent="generate">
      <label class="field"><span>{{t('network.export.mode')}}</span><select v-model="mode" :disabled="busy"><option value="isolated">{{t('network.export.isolated')}}</option><option v-if="core?.kind === 'xray' || core?.kind === 'sing_box'" value="merged">{{t('network.export.merged')}}</option></select></label>
      <button class="btn" :disabled="busy">{{busy ? t('network.export.generating') : t('network.export.generate')}}</button>
    </form>
    <p v-if="error" class="message error" role="alert">{{error}}</p>
    <section v-if="result" class="form-grid">
      <p class="hint-box">{{t('network.export.notApplied')}}</p>
      <article v-for="(artifact, index) in result.artifacts" :key="artifact.filename" class="card card-pad">
        <h3>{{artifact.filename}}</h3>
        <p>{{t('network.export.configurations')}}: {{artifact.configurations.map(row => `#${row.configuration_id} · ${t('network.export.revision')} ${row.revision}`).join(', ')}}</p>
        <label class="field"><span>{{t('network.export.sha')}}</span><input :value="artifact.sha256" readonly /></label>
        <details><summary>{{t('network.export.preview')}}</summary><label class="field"><textarea :value="artifact.content" readonly rows="12" spellcheck="false" /></label></details>
        <button type="button" class="btn secondary" @click="download(index)">{{t('network.export.download')}}</button>
      </article>
    </section>
  </Modal>
</template>
