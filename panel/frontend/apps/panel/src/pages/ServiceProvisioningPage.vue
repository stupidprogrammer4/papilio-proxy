<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type ManagedCore, type ManagedInbound, type ManagedService, type ManagedServicePage, type ManagedServiceCreate } from "@papilio/api";
import ManagedRecordPicker from "../components/ManagedRecordPicker.vue";
import XrayCoreSetup from "../components/XrayCoreSetup.vue";
import XrayInboundSetup from "../components/XrayInboundSetup.vue";

const { t } = useI18n();
const core = ref<ManagedCore | null>(null);
const inbound = ref<ManagedInbound | null>(null);
const selected = ref<ManagedService | null>(null);
const services = ref<ManagedServicePage>({ items: [], count: 0, page: 1, page_size: 20 });
const name = ref("");
const level = ref<number | "">("");
const identifier = ref("");
const subscription = ref("");
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
let currentSearch = { q: "", page: 1, page_size: 20 };
let requestKey = newRequestKey();
onBeforeUnmount(() => lifetime.abort());
watch(() => core.value?.id, () => { inbound.value = null; });

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
    services.value = await request<ManagedServicePage>(`/v1/services?${query(search)}`, "GET", undefined, { signal: lifetime.signal });
    currentSearch = search;
  });
}
async function select(id: string): Promise<void> {
  await perform(async () => {
    subscription.value = "";
    selected.value = await request<ManagedService>(`/v1/services/${id}`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function refresh(): Promise<void> {
  const service = selected.value;
  if (service) await select(service.id);
}
async function create(): Promise<void> {
  const parent = core.value;
  const endpoint = inbound.value;
  if (!parent || !endpoint || endpoint.core_id !== parent.id) return;
  const input: ManagedServiceCreate = {
    request_key: requestKey, core_id: parent.id, inbound_id: endpoint.id, name: name.value,
    user_level: level.value === "" ? null : level.value, identifier: identifier.value || null,
  };
  await perform(async () => {
    subscription.value = "";
    selected.value = await request<ManagedService>("/v1/services", "POST", input, { signal: lifetime.signal });
    requestKey = newRequestKey();
    name.value = "";
    identifier.value = "";
    services.value = await request<ManagedServicePage>(`/v1/services?${query(currentSearch)}`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function subscriptionLink(): Promise<void> {
  const service = selected.value;
  if (!service) return;
  await perform(async () => {
    subscription.value = "";
    const result = await request<{ url: string }>(`/v1/services/${service.id}/subscription`, "GET", undefined, { signal: lifetime.signal });
    subscription.value = result.url;
  });
}
onMounted(async () => { await load({ q: "", page: 1, page_size: 20 }); });
</script>

<template>
  <div class="stack">
    <header class="page-heading"><h1 data-testid="service-title">{{ t('serviceSetup.title') }}</h1><p>{{ t('serviceSetup.help') }}</p></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <section v-if="selected" class="card card-pad form-grid" data-testid="service-detail">
      <h2>{{ selected.name }}</h2>
      <p data-testid="service-status" aria-live="polite">{{ t(`foundation.states.${selected.status}`) }} · {{ t('foundation.attempts') }}: {{ selected.attempts }}</p>
      <p v-if="selected.error_code" role="status">{{ t('serviceSetup.executionError') }}: <code>{{ selected.error_code }}</code></p>
      <p>{{ t('serviceSetup.statusHelp') }}</p>
      <button class="btn secondary" data-testid="service-refresh" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
      <button class="btn" data-testid="service-subscription" :disabled="busy || selected.status !== 'succeeded'" @click="subscriptionLink">{{ t('serviceSetup.subscription') }}</button>
      <label v-if="subscription" class="field"><span>{{ t('serviceSetup.privateLink') }}</span><input :value="subscription" data-testid="subscription-url" readonly dir="ltr" @focus="($event.target as HTMLInputElement).select()" /></label>
    </section>
    <section class="card card-pad">
      <ManagedRecordPicker data-testid="service-picker" :title="t('serviceSetup.existing')" :items="services.items.map(item => ({ id: item.id, label: item.name }))" :count="services.count" :page="services.page" :page-size="services.page_size" :selected-id="selected?.id" :busy="busy" @search="load" @select="select" />
    </section>
    <fieldset class="stack" :disabled="busy">
      <legend>{{ t('serviceSetup.newService') }}</legend>
      <XrayCoreSetup v-model="core" />
      <XrayInboundSetup v-if="core" :key="core.id" v-model="inbound" :core="core" />
      <section class="card card-pad form-grid">
        <h2>{{ t('serviceSetup.create') }}</h2>
        <p v-if="!core || !inbound">{{ t('serviceSetup.chooseFirst') }}</p>
        <form @submit.prevent="create"><fieldset class="form-grid" :disabled="busy || !core || !inbound">
          <label class="field"><span>{{ t('serviceSetup.name') }}</span><input v-model="name" data-testid="service-name" required maxlength="80" /></label>
          <details><summary>{{ t('serviceSetup.advanced') }}</summary>
            <label class="field"><span>{{ t('serviceSetup.level') }}</span><input v-model.number="level" type="number" min="0" max="4294967295" step="1" :placeholder="String(core?.xray.default_user_level ?? '')" /></label>
            <label class="field"><span>{{ t('serviceSetup.identifier') }}</span><input v-model="identifier" dir="ltr" maxlength="36" pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" autocomplete="off" /></label>
          </details>
          <button class="btn" data-testid="service-create" type="submit">{{ t('serviceSetup.create') }}</button>
        </fieldset></form>
      </section>
    </fieldset>
  </div>
</template>
