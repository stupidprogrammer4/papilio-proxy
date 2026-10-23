<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type CustomerAccount, type CustomerAccountPage } from "@papilio/api";
import ManagedRecordPicker from "../components/ManagedRecordPicker.vue";
import CustomerWalletAccount from "../components/CustomerWalletAccount.vue";
import CustomerServiceOrders from "../components/CustomerServiceOrders.vue";
import CustomerManualInvoices from "../components/CustomerManualInvoices.vue";

const { t } = useI18n();
const customers = ref<CustomerAccountPage>({ items: [], count: 0, page: 1, page_size: 20 });
const selected = ref<CustomerAccount | null>(null);
const name = ref("");
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
let currentSearch = { q: "", page: 1, page_size: 20 };
let requestKey = newRequestKey();
onBeforeUnmount(() => lifetime.abort());

async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try { await action(); }
  catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("serviceSetup.failed"); }
  finally { busy.value = false; }
}
async function load(search: { q: string; page: number; page_size: number }): Promise<void> {
  await perform(async () => {
    customers.value = await request<CustomerAccountPage>(`/v1/customer-accounts?${query(search)}`, "GET", undefined, { signal: lifetime.signal });
    currentSearch = search;
  });
}
async function select(id: string): Promise<void> {
  await perform(async () => {
    selected.value = await request<CustomerAccount>(`/v1/customer-accounts/${id}`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function create(): Promise<void> {
  await perform(async () => {
    selected.value = await request<CustomerAccount>("/v1/customer-accounts", "POST", { request_key: requestKey, name: name.value }, { signal: lifetime.signal });
    requestKey = newRequestKey();
    name.value = "";
    customers.value = await request<CustomerAccountPage>(`/v1/customer-accounts?${query(currentSearch)}`, "GET", undefined, { signal: lifetime.signal });
  });
}
onMounted(async () => { await load({ q: "", page: 1, page_size: 20 }); });
</script>

<template>
  <div class="stack">
    <header class="page-heading"><h1 data-testid="sales-title">{{ t('sales.title') }}</h1><p>{{ t('sales.help') }}</p></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <section class="card card-pad">
      <form @submit.prevent="create"><fieldset class="form-grid" :disabled="busy">
        <label class="field"><span>{{ t('sales.customerName') }}</span><input v-model="name" data-testid="customer-name" required maxlength="80" /></label>
        <button class="btn" data-testid="customer-create" type="submit">{{ t('sales.createCustomer') }}</button>
      </fieldset></form>
    </section>
    <section class="card card-pad">
      <ManagedRecordPicker data-testid="customer-picker" :title="t('sales.customers')" :items="customers.items.map(item => ({ id: item.id, label: item.name }))" :count="customers.count" :page="customers.page" :page-size="customers.page_size" :selected-id="selected?.id" :busy="busy" @search="load" @select="select" />
    </section>
    <section v-if="selected" class="stack">
      <h2 data-testid="customer-selected">{{ selected.name }}</h2>
      <CustomerWalletAccount :key="`wallet-${selected.id}`" :customer="selected" />
      <CustomerServiceOrders :key="`orders-${selected.id}`" :customer="selected" />
      <CustomerManualInvoices :key="`invoices-${selected.id}`" :customer="selected" />
    </section>
  </div>
</template>
