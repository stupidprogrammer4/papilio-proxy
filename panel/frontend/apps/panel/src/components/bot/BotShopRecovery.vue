<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type BotRecoveryKind, type BotWorkInspection, type BotMessageInspection, type BotWorkPage, type BotMessagePage } from "@papilio/api";
import ManagedRecordPicker from "../ManagedRecordPicker.vue";
import BotRecoveryDetail from "./BotRecoveryDetail.vue";

const props = defineProps<{ botId: string }>();
const { t } = useI18n();
const kind = ref<BotRecoveryKind>("work");
const status = ref("");
const selectedId = ref("");
const records = ref<(BotWorkInspection | BotMessageInspection)[]>([]);
const count = ref(0); const page = ref(1); const pageSize = ref(20);
const busy = ref(false); const detailBusy = ref(false); const error = ref("");
const states = computed(() => kind.value === "work" ? ["queued", "running", "done", "failed", "cancelled"] : ["queued", "sending", "sent", "retry", "ambiguous", "failed", "cancelled"]);
const lifetime = new AbortController();
let currentSearch = { q: "", page: 1, page_size: 20 };
onBeforeUnmount(() => lifetime.abort());

function recordLabel(record: BotWorkInspection | BotMessageInspection): string {
  const received = "received_at" in record ? record.received_at : record.created_at;
  return `${record.id} · ${t(`botRecovery.states.${record.status}`)} · ${new Date(received).toLocaleString()}`;
}
async function load(search = currentSearch): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = ""; currentSearch = { ...search };
  try {
    const result = await request<BotWorkPage | BotMessagePage>(`/v1/bots/${props.botId}/shop/${kind.value}?${query({ ...search, status: status.value || undefined })}`, "GET", undefined, { signal: lifetime.signal });
    records.value = result.items; count.value = result.count; page.value = result.page; pageSize.value = result.page_size;
  } catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("bots.failed"); }
  finally { busy.value = false; }
}
async function changeKind(): Promise<void> {
  selectedId.value = ""; status.value = ""; records.value = []; count.value = 0;
  await load({ q: "", page: 1, page_size: pageSize.value });
}
onMounted(() => load());
</script>

<template>
  <section class="card card-pad form-grid">
    <h2 data-testid="shop-recovery-title">{{ t('botRecovery.title') }}</h2>
    <p>{{ t('botRecovery.help') }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <label class="field"><span>{{ t('botRecovery.kind') }}</span><select v-model="kind" data-testid="shop-recovery-kind" :disabled="busy || detailBusy" @change="changeKind"><option value="work">{{ t('botRecovery.work') }}</option><option value="messages">{{ t('botRecovery.messages') }}</option></select></label>
    <label class="field"><span>{{ t('botRecovery.status') }}</span><select v-model="status" :disabled="busy || detailBusy" @change="load({ ...currentSearch, page: 1 })"><option value="">{{ t('botRecovery.all') }}</option><option v-for="state in states" :key="state" :value="state">{{ t(`botRecovery.states.${state}`) }}</option></select></label>
    <button class="btn secondary" :disabled="busy || detailBusy" @click="load()">{{ t('foundation.refresh') }}</button>
    <ManagedRecordPicker :key="kind" data-testid="shop-recovery-picker" :title="t(kind === 'work' ? 'botRecovery.work' : 'botRecovery.messages')" :items="records.map(row => ({ id: row.id, label: recordLabel(row) }))" :count="count" :page="page" :page-size="pageSize" :selected-id="selectedId" :busy="busy || detailBusy" @search="load" @select="selectedId = $event" />
    <BotRecoveryDetail v-if="selectedId" :key="`${kind}:${selectedId}`" :bot-id="botId" :record-id="selectedId" :kind="kind" @changed="load()" @busy="detailBusy = $event" />
  </section>
</template>
