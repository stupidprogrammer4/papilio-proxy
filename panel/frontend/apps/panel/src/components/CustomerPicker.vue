<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { item, query, request, type Customer, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";

const props = withDefaults(defineProps<{ modelValue: number | null; locked?: boolean }>(), { locked: false });
const emit = defineEmits<{ "update:modelValue": [value: number | null] }>();
const auth = useAuth();
const { t } = useI18n();
const selected = ref<Customer | null>(null);
const rows = ref<Customer[]>([]);
const q = ref("");
const page = ref(1);
const pages = ref(1);
const total = ref(0);
const loading = ref(false);
const error = ref("");
const loaded = ref(false);
let searchSequence = 0;
let identitySequence = 0;

async function restore(id: number | null): Promise<void> {
  const sequence = ++identitySequence;
  selected.value = null;
  if (id === null || !auth.can("customers")) return;
  try {
    const row = await item<Customer>(`/v1/admin/customers/${id}`);
    if (sequence !== identitySequence || props.modelValue !== id) return;
    if (row.id !== id) throw new Error(t("customerPicker.wrongRecord"));
    selected.value = row;
  } catch (cause) {
    if (sequence === identitySequence) error.value = cause instanceof Error ? cause.message : t("customerPicker.readFailed");
  }
}

async function load(): Promise<void> {
  if (props.locked || !auth.can("customers")) return;
  const sequence = ++searchSequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await request<Page<Customer>>(`/v1/admin/customers?${query({ q: q.value.trim() || undefined, page: page.value })}`);
    if (sequence !== searchSequence) return;
    rows.value = result.data;
    pages.value = result.meta.pager?.total_pages ?? 1;
    total.value = result.meta.pager?.total_items ?? 0;
    loaded.value = true;
    const current = rows.value.find(row => row.id === props.modelValue);
    if (current) selected.value = current;
  } catch (cause) {
    if (sequence === searchSequence) error.value = cause instanceof Error ? cause.message : t("customerPicker.searchFailed");
  } finally {
    if (sequence === searchSequence) loading.value = false;
  }
}

function choose(row: Customer): void {
  if (props.locked) return;
  selected.value = row;
  emit("update:modelValue", row.id);
}
function search(): void { page.value = 1; void load(); }
watch(() => props.modelValue, restore);
watch(() => props.locked, () => { ++searchSequence; loading.value = false; });
onMounted(() => { void restore(props.modelValue); void load(); });
</script>

<template>
  <section :aria-label="t('customerPicker.region')" class="form-grid">
    <p v-if="modelValue !== null" class="message">{{ locked ? t('customerPicker.context') : t('customerPicker.selected') }}: {{ selected?.display_name ?? t('customerPicker.customerId', { id: modelValue }) }} · #{{ modelValue }}</p>
    <p v-else class="subtitle">{{ t('customerPicker.allCustomers') }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <template v-if="!locked && auth.can('customers')">
      <div class="toolbar">
        <label class="field"><span>{{ t('customerPicker.find') }}</span><input v-model="q" type="search" maxlength="120" :aria-label="t('customerPicker.find')" @keydown.enter.prevent="search" /></label>
        <button type="button" class="btn secondary" :disabled="loading" @click="search">{{ t('customerPicker.search') }}</button>
        <button v-if="modelValue !== null" type="button" class="btn secondary" @click="selected=null;emit('update:modelValue',null)">{{ t('customerPicker.allCustomers') }}</button>
      </div>
      <p v-if="loading" class="empty">{{ t('customerPicker.loading') }}</p>
      <p v-else-if="loaded && !error && !rows.length" class="empty">{{ t('customerPicker.empty') }}</p>
      <div v-if="rows.length" class="table-wrap"><table class="data-table"><thead><tr><th>{{ t('customerPicker.customer') }}</th><th>{{ t('customerPicker.status') }}</th><th>{{ t('customerPicker.selection') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{'selected-row':row.id===modelValue}"><td>{{row.display_name}} · #{{faNumber(row.id)}}</td><td>{{row.is_active?t('customerPicker.active'):t('customerPicker.inactive')}}</td><td><button type="button" class="btn small secondary" :aria-pressed="row.id===modelValue" @click="choose(row)">{{ t('customerPicker.selectId', { id: faNumber(row.id) }) }}</button></td></tr></tbody></table></div>
      <div v-if="loaded" class="pager"><button type="button" :disabled="loading||page<=1" @click="page--;load()">{{ t('customerPicker.previous') }}</button><span>{{ t('customerPicker.pageCount', { page: faNumber(page), pages: faNumber(pages), total: faNumber(total) }) }}</span><button type="button" :disabled="loading||page>=pages" @click="page++;load()">{{ t('customerPicker.next') }}</button></div>
    </template>
    <p v-else-if="!locked" class="subtitle">{{ t('customerPicker.accessRequired') }}</p>
  </section>
</template>
