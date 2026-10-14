<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { item, request, query, type HostGroup, type Page } from "@papilio/api";
import { faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";
const { t } = useI18n();
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
  <section><h3>{{ t("plans.bundle.title") }}</h3><p v-if="selected">{{ t("plans.bundle.selected", { title: selected.title, status: t(selected.is_enabled ? "plans.bundle.enabled" : "plans.bundle.inactive") }) }}</p><p v-else-if="modelValue !== null">{{ t("plans.bundle.group", { id: faNumber(modelValue) }) }}</p><p v-else>{{ t("plans.bundle.none") }}</p><p v-if="error" class="message error" role="alert">{{ error }}</p><div class="toolbar"><label class="field"><span>{{ t("plans.bundle.find") }}</span><input v-model="q" @keydown.enter.prevent="page = 1; load()" /></label><button type="button" class="btn secondary" @click="page = 1; load()">{{ t("plans.bundle.search") }}</button><button type="button" class="btn secondary" @click="selected = null; emit('update:modelValue', null)">{{ t("plans.bundle.clear") }}</button></div><div class="inline-actions"><button v-for="row in rows" :key="row.id" type="button" class="btn small secondary" :disabled="!row.is_enabled" :aria-pressed="modelValue === row.id" @click="choose(row)">{{ row.title }} · {{ t(row.is_enabled ? "plans.bundle.enabled" : "plans.bundle.inactive") }}</button></div><p v-if="state === 'loading'">{{ t("plans.bundle.loading") }}</p><p v-else-if="state === 'ready' && !rows.length">{{ t("plans.bundle.empty") }}</p><div v-if="state !== 'idle'" class="pager"><button type="button" :disabled="page <= 1" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button type="button" :disabled="page >= pages" @click="page++; load()">›</button></div></section>
</template>
