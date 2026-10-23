<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type ManagedCore, type ManagedInbound, type ServiceProduct, type ServiceProductPage, type ServiceProductDefinition } from "@papilio/api";
import ManagedRecordPicker from "../components/ManagedRecordPicker.vue";
import XrayCoreSetup from "../components/XrayCoreSetup.vue";
import XrayInboundSetup from "../components/XrayInboundSetup.vue";

const { t } = useI18n();
const products = ref<ServiceProductPage>({ items: [], count: 0, page: 1, page_size: 20 });
const selected = ref<ServiceProduct | null>(null);
const core = ref<ManagedCore | null>(null);
const inbound = ref<ManagedInbound | null>(null);
const name = ref("");
const price = ref("");
const level = ref<number | "">("");
const active = ref(true);
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
let currentSearch = { q: "", page: 1, page_size: 20 };
let requestKey = newRequestKey();
onBeforeUnmount(() => lifetime.abort());
watch(() => core.value?.id, () => { inbound.value = null; }, { flush: "sync" });

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
    products.value = await request<ServiceProductPage>(`/v1/products?${query(search)}`, "GET", undefined, { signal: lifetime.signal });
    currentSearch = search;
  });
}
async function select(id: string): Promise<void> {
  await perform(async () => {
    const product = await request<ServiceProduct>(`/v1/products/${id}`, "GET", undefined, { signal: lifetime.signal });
    const definition = product.offer.definition;
    const [parent, endpoint] = await Promise.all([
      request<ManagedCore>(`/v1/cores/${definition.core_id}`, "GET", undefined, { signal: lifetime.signal }),
      request<ManagedInbound>(`/v1/cores/${definition.core_id}/xray/inbounds/${definition.inbound_id}`, "GET", undefined, { signal: lifetime.signal }),
    ]);
    core.value = parent;
    inbound.value = endpoint;
    selected.value = product;
    name.value = definition.name;
    price.value = definition.price_minor;
    level.value = definition.user_level ?? "";
    active.value = definition.is_active;
  });
}
function fresh(): void {
  selected.value = null;
  name.value = "";
  price.value = "";
  level.value = "";
  active.value = true;
  requestKey = newRequestKey();
}
async function save(): Promise<void> {
  const parent = core.value;
  const endpoint = inbound.value;
  if (!parent || !endpoint || endpoint.core_id !== parent.id) return;
  const definition: ServiceProductDefinition = { name: name.value, core_id: parent.id, inbound_id: endpoint.id, currency: "IRR", price_minor: price.value, user_level: level.value === "" ? null : level.value, is_active: active.value };
  const current = selected.value;
  await perform(async () => {
    selected.value = current
      ? await request<ServiceProduct>(`/v1/products/${current.id}`, "PUT", { expected_revision: current.offer.revision, definition }, { signal: lifetime.signal })
      : await request<ServiceProduct>("/v1/products", "POST", { request_key: requestKey, definition }, { signal: lifetime.signal });
    requestKey = newRequestKey();
    products.value = await request<ServiceProductPage>(`/v1/products?${query(currentSearch)}`, "GET", undefined, { signal: lifetime.signal });
  });
}
onMounted(async () => { await load({ q: "", page: 1, page_size: 20 }); });
</script>

<template>
  <div class="stack">
    <header class="page-heading"><h1 data-testid="products-title">{{ t('productCatalog.title') }}</h1><p>{{ t('productCatalog.help') }}</p></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <section class="card card-pad">
      <ManagedRecordPicker data-testid="product-picker" :title="t('productCatalog.existing')" :items="products.items.map(item => ({ id: item.id, label: item.offer.definition.name }))" :count="products.count" :page="products.page" :page-size="products.page_size" :selected-id="selected?.id" :busy="busy" @search="load" @select="select" />
    </section>
    <fieldset class="stack" :disabled="busy">
      <legend>{{ t('productCatalog.configuration') }}</legend>
      <button class="btn secondary" type="button" @click="fresh">{{ t('productCatalog.new') }}</button>
      <p v-if="selected" data-testid="product-current">{{ selected.offer.definition.name }} · {{ t('productCatalog.revision') }} {{ selected.offer.revision }}</p>
      <XrayCoreSetup v-model="core" />
      <XrayInboundSetup v-if="core" :key="core.id" v-model="inbound" :core="core" />
      <section class="card card-pad">
        <form @submit.prevent="save"><fieldset class="form-grid" :disabled="busy || !core || !inbound">
          <label class="field"><span>{{ t('productCatalog.name') }}</span><input v-model="name" data-testid="product-name" required maxlength="80" /></label>
          <label class="field"><span>{{ t('productCatalog.price') }}</span><input v-model="price" data-testid="product-price" type="text" inputmode="numeric" pattern="[0-9]+" required maxlength="19" dir="ltr" /></label>
          <label><input v-model="active" type="checkbox" data-testid="product-active" /> {{ t('productCatalog.active') }}</label>
          <details><summary>{{ t('serviceSetup.advanced') }}</summary>
            <label class="field"><span>{{ t('serviceSetup.level') }}</span><input v-model.number="level" type="number" min="0" max="4294967295" step="1" /></label>
            <p v-if="selected">{{ t('productCatalog.savedLevel', { level: selected.offer.user_level }) }}</p>
          </details>
          <p>{{ t('productCatalog.snapshotHelp') }}</p>
          <button class="btn" type="submit" data-testid="product-save">{{ t(selected ? 'productCatalog.save' : 'productCatalog.create') }}</button>
        </fieldset></form>
      </section>
    </fieldset>
  </div>
</template>
