<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { query, request, type CoreInstance, type Page } from "@papilio/api";
import { faNumber } from "@papilio/ui";

const props = defineProps<{ nodeId: number; modelValue: CoreInstance | null }>();
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
    if (current === sequence && !controller.signal.aborted) error.value = cause instanceof Error ? cause.message : "Could not load cores.";
  } finally { if (current === sequence) loading.value = false; }
}
watch(() => props.nodeId, () => { page.value = 1; rows.value = []; void load(); });
onMounted(load);
onUnmounted(() => { ++sequence; active?.abort(); });
</script>
<template>
  <section class="form-grid">
    <h3>Core placement</h3>
    <p v-if="modelValue">Selected: <strong>{{modelValue.label}}</strong> · {{modelValue.kind}}</p>
    <p v-else>Choose automatically by protocol, or select an existing core on this node.</p>
    <div class="toolbar"><label class="field"><span>Search cores</span><input v-model="q" @keydown.enter.prevent="page=1;load()" /></label><button type="button" class="btn secondary" :disabled="loading" @click="page=1;load()">Search</button><button type="button" class="btn small secondary" @click="emit('update:modelValue',null)">Choose automatically</button></div>
    <p v-if="error" class="message error" role="alert">{{error}}</p>
    <p v-else-if="loading">Loading cores…</p>
    <div v-else class="inline-actions"><button v-for="row in rows" :key="row.id" type="button" class="btn small secondary" :aria-pressed="modelValue?.id===row.id" @click="emit('update:modelValue',row)">{{row.label}} · {{row.kind}}</button><p v-if="!rows.length">No cores match this search. Automatic placement remains available.</p></div>
    <div class="pager"><button type="button" :disabled="loading||page<=1" @click="page--;load()">‹</button><span>{{faNumber(page)}} / {{faNumber(pages)}}</span><button type="button" :disabled="loading||page>=pages" @click="page++;load()">›</button></div>
  </section>
</template>
