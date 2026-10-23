<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { request, query, type ManualInvoicePage, type ManualInvoiceState } from "@papilio/api";
import ManagedRecordPicker from "../components/ManagedRecordPicker.vue";
import ManualPaymentSettings from "../components/ManualPaymentSettings.vue";
import ManualInvoiceDetail from "../components/ManualInvoiceDetail.vue";

const { t } = useI18n();
const route = useRoute();
const invoices = ref<ManualInvoicePage>({ items: [], count: 0, page: 1, page_size: 20 });
const selectedId = ref(""); const status = ref<ManualInvoiceState | "">("review");
function queryId(value: unknown): string {
  return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) ? value : "";
}
const linkedInvoiceId = computed(() => queryId(route.query.invoice_id));
const initialReceiptId = computed(() => selectedId.value === linkedInvoiceId.value ? queryId(route.query.receipt_id) : "");
watch(linkedInvoiceId, value => { selectedId.value = value; }, { immediate: true });
const busy = ref(false); const error = ref("");
const lifetime = new AbortController();
let currentSearch = { q: "", page: 1, page_size: 20 };
onBeforeUnmount(() => lifetime.abort());
async function load(search: typeof currentSearch): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try {
    invoices.value = await request<ManualInvoicePage>(`/v1/invoices?${query({ ...search, status: status.value })}`, "GET", undefined, { signal: lifetime.signal });
    currentSearch = search;
  } catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("serviceSetup.failed"); }
  finally { busy.value = false; }
}
onMounted(async () => { await load(currentSearch); });
</script>

<template>
  <div class="stack">
    <header class="page-heading"><h1 data-testid="invoices-title">{{ t('invoices.title') }}</h1><p>{{ t('invoices.help') }}</p></header>
    <ManualPaymentSettings />
    <section class="card card-pad form-grid">
      <p v-if="error" class="message error" role="alert">{{ error }}</p>
      <label class="field"><span>{{ t('invoices.statusFilter') }}</span><select v-model="status" data-testid="invoice-status-filter" :disabled="busy" @change="load({ ...currentSearch, page: 1 })">
        <option value="">{{ t('invoices.allStates') }}</option><option v-for="state in (['open', 'review', 'rejected', 'settled'] as const)" :key="state" :value="state">{{ t(`invoices.states.${state}`) }}</option>
      </select></label>
      <ManagedRecordPicker data-testid="invoice-picker" :title="t('invoices.queue')" :items="invoices.items.map(item => ({ id: item.id, label: `${item.id} · ${item.amount_due_minor} ${item.currency}` }))" :count="invoices.count" :page="invoices.page" :page-size="invoices.page_size" :selected-id="selectedId" :busy="busy" @search="load" @select="selectedId = $event" />
    </section>
    <ManualInvoiceDetail v-if="selectedId" :key="`${selectedId}:${initialReceiptId}`" :invoice-id="selectedId" :initial-receipt-id="initialReceiptId" @changed="load(currentSearch)" />
  </div>
</template>
