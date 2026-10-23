<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type CustomerAccount, type ManualInvoice, type ManualInvoicePage } from "@papilio/api";
import ManagedRecordPicker from "./ManagedRecordPicker.vue";
import ManualInvoiceDetail from "./ManualInvoiceDetail.vue";

const props = defineProps<{ customer: CustomerAccount }>();
const { t } = useI18n();
const invoices = ref<ManualInvoicePage>({ items: [], count: 0, page: 1, page_size: 20 });
const selectedId = ref(""); const amount = ref(""); const busy = ref(false); const error = ref("");
const lifetime = new AbortController();
let requestKey = newRequestKey();
let currentSearch = { q: "", page: 1, page_size: 20 };
onBeforeUnmount(() => lifetime.abort());
async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); }
  catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("serviceSetup.failed"); }
  finally { busy.value = false; }
}
async function load(search: typeof currentSearch): Promise<void> {
  await perform(async () => { invoices.value = await request<ManualInvoicePage>(`/v1/invoices?${query({ ...search, customer_id: props.customer.id })}`, "GET", undefined, { signal: lifetime.signal }); currentSearch = search; });
}
async function issue(): Promise<void> {
  const body = { request_key: requestKey, customer_id: props.customer.id, base_amount_minor: amount.value };
  await perform(async () => {
    const result = await request<ManualInvoice>("/v1/invoices", "POST", body, { signal: lifetime.signal });
    requestKey = newRequestKey(); selectedId.value = result.id; amount.value = "";
    invoices.value = await request<ManualInvoicePage>(`/v1/invoices?${query({ ...currentSearch, customer_id: props.customer.id })}`, "GET", undefined, { signal: lifetime.signal });
  });
}
onMounted(async () => { await load(currentSearch); });
</script>

<template>
  <section class="stack">
    <div class="card card-pad form-grid">
      <h3>{{ t('invoices.customerTitle') }}</h3><p>{{ t('invoices.issueHelp') }} <RouterLink to="/invoices">{{ t('invoices.settingsTitle') }}</RouterLink></p>
      <p v-if="error" class="message error" role="alert">{{ error }}</p>
      <form @submit.prevent="issue"><fieldset class="form-grid" :disabled="busy">
        <label class="field"><span>{{ t('invoices.baseAmount') }}</span><input v-model="amount" data-testid="invoice-amount" type="text" inputmode="numeric" pattern="[0-9]+" maxlength="19" required dir="ltr" /></label>
        <button class="btn" type="submit" data-testid="invoice-issue">{{ t('invoices.issue') }}</button>
      </fieldset></form>
      <ManagedRecordPicker :title="t('invoices.customerTitle')" :items="invoices.items.map(item => ({ id: item.id, label: `${item.id} · ${item.amount_due_minor} ${item.currency}` }))" :count="invoices.count" :page="invoices.page" :page-size="invoices.page_size" :selected-id="selectedId" :busy="busy" @search="load" @select="selectedId = $event" />
    </div>
    <ManualInvoiceDetail v-if="selectedId" :key="selectedId" :invoice-id="selectedId" @changed="load(currentSearch)" />
  </section>
</template>
