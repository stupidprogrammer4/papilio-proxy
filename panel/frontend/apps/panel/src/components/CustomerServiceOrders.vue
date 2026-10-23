<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type CustomerAccount, type ServiceProduct, type ServiceProductPage, type ServiceOrder, type ServiceOrderPage, type ServicePurchase, type ManagedService } from "@papilio/api";
import ManagedRecordPicker from "./ManagedRecordPicker.vue";

const props = defineProps<{ customer: CustomerAccount }>();
const { t } = useI18n();
const products = ref<ServiceProductPage>({ items: [], count: 0, page: 1, page_size: 20 });
const orders = ref<ServiceOrderPage>({ items: [], count: 0, page: 1, page_size: 20 });
const product = ref<ServiceProduct | null>(null);
const selected = ref<ServiceOrder | null>(null);
const service = ref<ManagedService | null>(null);
const name = ref("");
const subscription = ref("");
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
let orderSearch = { q: "", page: 1, page_size: 20 };
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
async function loadProducts(search: { q: string; page: number; page_size: number }): Promise<void> {
  await perform(async () => { products.value = await request<ServiceProductPage>(`/v1/products?${query({ ...search, active_only: true })}`, "GET", undefined, { signal: lifetime.signal }); });
}
async function loadOrders(search: { q: string; page: number; page_size: number }): Promise<void> {
  await perform(async () => {
    orders.value = await request<ServiceOrderPage>(`/v1/orders?${query({ ...search, customer_id: props.customer.id })}`, "GET", undefined, { signal: lifetime.signal });
    orderSearch = search;
  });
}
async function chooseProduct(id: string): Promise<void> {
  await perform(async () => {
    product.value = await request<ServiceProduct>(`/v1/products/${id}`, "GET", undefined, { signal: lifetime.signal });
    if (!name.value) name.value = product.value.offer.definition.name;
  });
}
async function readOrder(id: string): Promise<void> {
  subscription.value = "";
  service.value = null;
  selected.value = await request<ServiceOrder>(`/v1/orders/${id}`, "GET", undefined, { signal: lifetime.signal });
  if (selected.value.service_id) service.value = await request<ManagedService>(`/v1/services/${selected.value.service_id}`, "GET", undefined, { signal: lifetime.signal });
}
async function select(id: string): Promise<void> { await perform(async () => { await readOrder(id); }); }
async function refresh(): Promise<void> {
  const current = selected.value;
  if (current) await select(current.id);
}
async function purchase(): Promise<void> {
  const current = product.value;
  if (!current) return;
  const input: ServicePurchase = { request_key: requestKey, customer_id: props.customer.id, product_id: current.id, expected_revision: current.offer.revision, service_name: name.value };
  await perform(async () => {
    const result = await request<ServiceOrder>("/v1/orders", "POST", input, { signal: lifetime.signal });
    requestKey = newRequestKey();
    name.value = "";
    await readOrder(result.id);
    orders.value = await request<ServiceOrderPage>(`/v1/orders?${query({ ...orderSearch, customer_id: props.customer.id })}`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function link(): Promise<void> {
  const current = selected.value;
  if (!current?.service_id) return;
  await perform(async () => {
    subscription.value = "";
    const result = await request<{ url: string }>(`/v1/services/${current.service_id}/subscription`, "GET", undefined, { signal: lifetime.signal });
    subscription.value = result.url;
  });
}
onMounted(async () => {
  await perform(async () => {
    const [productPage, orderPage] = await Promise.all([
      request<ServiceProductPage>("/v1/products?active_only=true", "GET", undefined, { signal: lifetime.signal }),
      request<ServiceOrderPage>(`/v1/orders?${query({ customer_id: props.customer.id })}`, "GET", undefined, { signal: lifetime.signal }),
    ]);
    products.value = productPage;
    orders.value = orderPage;
  });
});
</script>

<template>
  <section class="card card-pad form-grid">
    <h3>{{ t('serviceOrders.title') }}</h3><p>{{ t('serviceOrders.help') }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <ManagedRecordPicker data-testid="purchase-product-picker" :title="t('productCatalog.title')" :items="products.items.map(item => ({ id: item.id, label: item.offer.definition.name }))" :count="products.count" :page="products.page" :page-size="products.page_size" :selected-id="product?.id" :busy="busy" @search="loadProducts" @select="chooseProduct" />
    <p v-if="product">{{ t('productCatalog.price') }}: <span dir="ltr">{{ product.offer.definition.price_minor }} IRR</span></p>
    <form @submit.prevent="purchase"><fieldset class="form-grid" :disabled="busy || !product || !product.offer.definition.is_active">
      <label class="field"><span>{{ t('serviceOrders.serviceName') }}</span><input v-model="name" data-testid="purchase-service-name" required maxlength="80" /></label>
      <button class="btn" type="submit" data-testid="purchase-submit">{{ t('serviceOrders.buy') }}</button>
    </fieldset></form>
    <section v-if="selected" class="form-grid" data-testid="purchase-detail">
      <h3>{{ selected.service_name }}</h3>
      <p>{{ t('serviceOrders.accepted') }}: <span dir="ltr">{{ selected.terms.price_minor }} {{ selected.terms.currency }}</span></p>
      <p v-if="service" data-testid="purchase-service-status" aria-live="polite">{{ t(`foundation.states.${service.status}`) }} <span v-if="service.error_code">({{ service.error_code }})</span></p>
      <p>{{ t('serviceOrders.progressHelp') }}</p>
      <button class="btn secondary" data-testid="purchase-refresh" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
      <button class="btn" data-testid="purchase-subscription" :disabled="busy || service?.status !== 'succeeded'" @click="link">{{ t('serviceSetup.subscription') }}</button>
      <label v-if="subscription" class="field"><span>{{ t('serviceSetup.privateLink') }}</span><input :value="subscription" data-testid="purchase-url" readonly dir="ltr" @focus="($event.target as HTMLInputElement).select()" /></label>
    </section>
    <ManagedRecordPicker data-testid="purchase-history" :title="t('serviceOrders.history')" :items="orders.items.map(item => ({ id: item.id, label: item.service_name }))" :count="orders.count" :page="orders.page" :page-size="orders.page_size" :selected-id="selected?.id" :busy="busy" @search="loadOrders" @select="select" />
  </section>
</template>
