<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { item, request, query, type HostGroup, type Page } from "@papilio/api";
import { faNumber } from "@papilio/ui";
const props = defineProps<{ modelValue: number | null }>(); const emit = defineEmits<{ "update:modelValue": [value: number | null] }>();
const selected = ref<HostGroup | null>(null); const rows = ref<HostGroup[]>([]); const page = ref(1); const pages = ref(1); const q = ref(""); const state = ref<"idle" | "loading" | "ready" | "error">("idle"); const error = ref("");
async function load(): Promise<void> {
  state.value = "loading"; error.value = ""; const requested = page.value;
  try { const result = await request<Page<HostGroup>>(`/v1/admin/network/host-groups?${query({ page: requested, q: q.value })}`); if (requested !== page.value) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; state.value = "ready"; }
  catch (cause) { state.value = "error"; error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
async function restore(id: number | null): Promise<void> {
  if (id === null) { selected.value = null; return; }
  try { const result = await item<HostGroup>(`/v1/admin/network/host-groups/${id}`); if (props.modelValue === id) selected.value = result; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
function choose(row: HostGroup): void { selected.value = row; emit("update:modelValue", row.id); }
watch(() => props.modelValue, restore); onMounted(() => { void restore(props.modelValue); });
</script>
<template>
  <section><h3>Configuration bundle</h3><p v-if="selected">Selected: {{ selected.title }} · {{ selected.is_enabled ? 'Enabled' : 'Inactive' }}</p><p v-else-if="modelValue !== null">Group {{ faNumber(modelValue) }}</p><p v-else>No bundle selected. Only explicitly assigned connections will be delivered.</p><p v-if="error" class="message error" role="alert">{{ error }}</p><div class="toolbar"><label class="field"><span>Find a delivery group</span><input v-model="q" @keydown.enter.prevent="page = 1; load()" /></label><button type="button" class="btn secondary" @click="page = 1; load()">Search groups</button><button type="button" class="btn secondary" @click="selected = null; emit('update:modelValue', null)">Clear bundle selection</button></div><div class="inline-actions"><button v-for="row in rows" :key="row.id" type="button" class="btn small secondary" :disabled="!row.is_enabled" :aria-pressed="modelValue === row.id" @click="choose(row)">{{ row.title }} · {{ row.is_enabled ? 'Enabled' : 'Inactive' }}</button></div><p v-if="state === 'loading'">Loading…</p><p v-else-if="state === 'ready' && !rows.length">No groups found.</p><div v-if="state !== 'idle'" class="pager"><button type="button" :disabled="page <= 1" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button type="button" :disabled="page >= pages" @click="page++; load()">›</button></div></section>
</template>
