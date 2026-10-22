<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type ManagedCore, type ManagedInbound, type ManagedInboundPage, type XrayInboundCreate } from "@papilio/api";
import ManagedRecordPicker from "./ManagedRecordPicker.vue";

const props = defineProps<{ core: ManagedCore }>();
const selected = defineModel<ManagedInbound | null>({ required: true });
const { t } = useI18n();
const inbounds = ref<ManagedInboundPage>({ items: [], count: 0, page: 1, page_size: 20 });
const tag = ref("");
const host = ref("");
const port = ref<number | "">("");
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
let currentSearch = { q: "", page: 1, page_size: 20 };
let requestKey = newRequestKey();
onBeforeUnmount(() => lifetime.abort());
const path = `/v1/cores/${props.core.id}/xray/inbounds`;

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
    inbounds.value = await request<ManagedInboundPage>(`${path}?${query(search)}`, "GET", undefined, { signal: lifetime.signal });
    currentSearch = search;
  });
}
async function select(id: string): Promise<void> {
  await perform(async () => {
    selected.value = await request<ManagedInbound>(`${path}/${id}`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function create(): Promise<void> {
  if (port.value === "") return;
  const input: XrayInboundCreate = { request_key: requestKey, tag: tag.value, public_host: host.value, port: port.value };
  await perform(async () => {
    selected.value = await request<ManagedInbound>(path, "POST", input, { signal: lifetime.signal });
    requestKey = newRequestKey();
    tag.value = "";
    inbounds.value = await request<ManagedInboundPage>(`${path}?${query(currentSearch)}`, "GET", undefined, { signal: lifetime.signal });
  });
}
onMounted(async () => { await load({ q: "", page: 1, page_size: 20 }); });
</script>

<template>
  <section class="card card-pad form-grid">
    <h2>{{ t('serviceSetup.inbound') }}</h2>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="selected" data-testid="selected-inbound">{{ t('serviceSetup.selected') }}: {{ selected.tag }} · <span dir="ltr">{{ selected.public_host }}:{{ selected.port }}</span></p>
    <ManagedRecordPicker data-testid="inbound-picker" :title="t('serviceSetup.chooseInbound')" :items="inbounds.items.map(item => ({ id: item.id, label: `${item.tag} · ${item.public_host}:${item.port}` }))" :count="inbounds.count" :page="inbounds.page" :page-size="inbounds.page_size" :selected-id="selected?.id" :busy="busy" @search="load" @select="select" />
    <details>
      <summary data-testid="inbound-registration">{{ t('serviceSetup.registerInbound') }}</summary>
      <p>{{ t('serviceSetup.inboundHelp') }}</p>
      <form @submit.prevent="create"><fieldset class="form-grid" :disabled="busy">
        <label class="field"><span>{{ t('serviceSetup.tag') }}</span><input v-model="tag" data-testid="inbound-tag" required maxlength="255" dir="ltr" /></label>
        <label class="field"><span>{{ t('serviceSetup.host') }}</span><input v-model="host" data-testid="inbound-host" required maxlength="255" dir="ltr" /></label>
        <label class="field"><span>{{ t('serviceSetup.port') }}</span><input v-model.number="port" data-testid="inbound-port" required type="number" min="1" max="65535" step="1" /></label>
        <button class="btn" type="submit" data-testid="inbound-create">{{ t('serviceSetup.registerInbound') }}</button>
      </fieldset></form>
    </details>
  </section>
</template>
