<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { query, request, type CoreInstance, type Page } from "@papilio/api";
import { faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";

const props = defineProps<{ nodeId: number; modelValue: CoreInstance | null }>();
const { t } = useI18n();
const emit = defineEmits<{ "update:modelValue": [value: CoreInstance | null] }>();
const rows = ref<CoreInstance[]>([]), q = ref(""), page = ref(1), pages = ref(1);
const loading = ref(false), error = ref("");
let sequence = 0, active: AbortController | null = null;
async function load(): Promise<void> {
  const current = ++sequence;
  active?.abort(); const controller = new AbortController(); active = controller;
  loading.value = true; error.value = "";
  try {
    const result = await request<Page<CoreInstance>>(`/v1/admin/network/nodes/${props.nodeId}/cores?${query({q:q.value,page:page.value})}`, "GET", undefined, {signal:controller.signal});
    if (current !== sequence) return;
    rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1;
  } catch (cause) {
    if (current === sequence && !controller.signal.aborted) error.value = cause instanceof Error ? cause.message : t("configurationCorePicker.failed");
  } finally { if (current === sequence) loading.value = false; }
}
watch(() => props.nodeId, () => { page.value = 1; rows.value = []; void load(); });
onMounted(load);
onUnmounted(() => { ++sequence; active?.abort(); });
</script>
<template>
  <section class="form-grid">
    <h3>{{ t("configurationCorePicker.title") }}</h3>
    <p v-if="modelValue">{{ t("configurationCorePicker.selected", { label: modelValue.label, kind: modelValue.kind }) }}</p>
    <p v-else>{{ t("configurationCorePicker.description") }}</p>
    <div class="toolbar"><label class="field"><span>{{ t("configurationCorePicker.search") }}</span><input v-model="q" @keydown.enter.prevent="page=1;load()" /></label><button type="button" class="btn secondary" :disabled="loading" @click="page=1;load()">{{ t("configurationCorePicker.search") }}</button><button type="button" class="btn small secondary" @click="emit('update:modelValue',null)">{{ t("configurationCorePicker.automatic") }}</button></div>
    <p v-if="error" class="message error" role="alert">{{error}}</p>
    <p v-else-if="loading">{{ t("configurationCorePicker.loading") }}</p>
    <div v-else class="inline-actions"><button v-for="row in rows" :key="row.id" type="button" class="btn small secondary" :aria-pressed="modelValue?.id===row.id" @click="emit('update:modelValue',row)">{{row.label}} · {{row.kind}}</button><p v-if="!rows.length">{{ t("configurationCorePicker.empty") }}</p></div>
    <div class="pager"><button type="button" :disabled="loading||page<=1" @click="page--;load()">‹</button><span>{{ t("configurationCorePicker.page", { page: faNumber(page), pages: faNumber(pages) }) }}</span><button type="button" :disabled="loading||page>=pages" @click="page++;load()">›</button></div>
  </section>
</template>
