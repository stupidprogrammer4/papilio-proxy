<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type ManagedCore, type ManagedCorePage, type ManagedNode, type ManagedNodePage, type XrayCoreCreate } from "@papilio/api";
import ManagedRecordPicker from "./ManagedRecordPicker.vue";

const selected = defineModel<ManagedCore | null>({ required: true });
const { t } = useI18n();
const cores = ref<ManagedCorePage>({ items: [], count: 0, page: 1, page_size: 20 });
const nodes = ref<ManagedNodePage>({ items: [], count: 0, page: 1, page_size: 20 });
const node = ref<ManagedNode | null>(null);
const name = ref("");
const level = ref(0);
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
let coreSearch = { q: "", page: 1, page_size: 20 };
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
async function loadCores(search: { q: string; page: number; page_size: number }): Promise<void> {
  await perform(async () => {
    cores.value = await request<ManagedCorePage>(`/v1/cores?${query(search)}`, "GET", undefined, { signal: lifetime.signal });
    coreSearch = search;
  });
}
async function loadNodes(search: { q: string; page: number; page_size: number }): Promise<void> {
  await perform(async () => {
    nodes.value = await request<ManagedNodePage>(`/v1/nodes?${query(search)}`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function selectCore(id: string): Promise<void> {
  await perform(async () => {
    selected.value = await request<ManagedCore>(`/v1/cores/${id}`, "GET", undefined, { signal: lifetime.signal });
  });
}
function selectNode(id: string): void { node.value = nodes.value.items.find(item => item.id === id) ?? null; }
async function create(): Promise<void> {
  const parent = node.value;
  if (!parent) return;
  await perform(async () => {
    const input: XrayCoreCreate = { request_key: requestKey, node_id: parent.id, name: name.value, default_user_level: level.value };
    selected.value = await request<ManagedCore>("/v1/cores/xray", "POST", input, { signal: lifetime.signal });
    requestKey = newRequestKey();
    name.value = "";
    cores.value = await request<ManagedCorePage>(`/v1/cores?${query(coreSearch)}`, "GET", undefined, { signal: lifetime.signal });
  });
}
onMounted(async () => {
  await perform(async () => {
    const [corePage, nodePage] = await Promise.all([
      request<ManagedCorePage>("/v1/cores", "GET", undefined, { signal: lifetime.signal }),
      request<ManagedNodePage>("/v1/nodes", "GET", undefined, { signal: lifetime.signal }),
    ]);
    cores.value = corePage;
    nodes.value = nodePage;
  });
});
</script>

<template>
  <section class="card card-pad form-grid">
    <h2>{{ t('serviceSetup.core') }}</h2>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="selected" data-testid="selected-core">{{ t('serviceSetup.selected') }}: {{ selected.name }}</p>
    <ManagedRecordPicker data-testid="core-picker" :title="t('serviceSetup.chooseCore')" :items="cores.items.map(item => ({ id: item.id, label: item.name }))" :count="cores.count" :page="cores.page" :page-size="cores.page_size" :selected-id="selected?.id" :busy="busy" @search="loadCores" @select="selectCore" />
    <details>
      <summary data-testid="core-registration">{{ t('serviceSetup.registerCore') }}</summary>
      <p>{{ t('serviceSetup.coreHelp') }}</p>
      <ManagedRecordPicker data-testid="core-node-picker" :title="t('serviceSetup.chooseNode')" :items="nodes.items.map(item => ({ id: item.id, label: item.name }))" :count="nodes.count" :page="nodes.page" :page-size="nodes.page_size" :selected-id="node?.id" :busy="busy" @search="loadNodes" @select="selectNode" />
      <p v-if="node">{{ t('serviceSetup.selected') }}: {{ node.name }}</p>
      <form @submit.prevent="create">
        <fieldset class="form-grid" :disabled="busy || !node">
          <label class="field"><span>{{ t('serviceSetup.name') }}</span><input v-model="name" data-testid="core-name" required maxlength="80" /></label>
          <details><summary>{{ t('serviceSetup.advanced') }}</summary><label class="field"><span>{{ t('serviceSetup.defaultLevel') }}</span><input v-model.number="level" type="number" min="0" max="4294967295" step="1" required /></label></details>
          <button class="btn" type="submit" data-testid="core-create">{{ t('serviceSetup.registerCore') }}</button>
        </fieldset>
      </form>
    </details>
  </section>
</template>
