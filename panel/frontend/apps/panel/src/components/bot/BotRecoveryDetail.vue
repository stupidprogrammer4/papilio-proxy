<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, request, query, type BotRecoveryAction, type BotRecoveryKind, type BotWorkInspection, type BotMessageInspection, type BotWorkRecoveryPage, type BotMessageRecoveryPage, type BotWorkRecoveryResult, type BotMessageRecoveryResult } from "@papilio/api";

const props = defineProps<{ botId: string; recordId: string; kind: BotRecoveryKind }>();
const emit = defineEmits<{ changed: []; busy: [value: boolean] }>();
const { t } = useI18n();
const record = ref<BotWorkInspection | BotMessageInspection | null>(null);
const history = ref<BotWorkRecoveryPage | BotMessageRecoveryPage>({ items: [], count: 0, page: 1, page_size: 10 });
const note = ref(""); const search = ref(""); const historyPageSize = ref(10);
const busy = ref(false); const error = ref("");
const invoiceId = computed(() => record.value && "invoice_id" in record.value ? record.value.invoice_id : null);
const lifetime = new AbortController();
const endpoint = `/v1/bots/${props.botId}/shop/${props.kind}/${props.recordId}`;
let requestKey = newRequestKey();
onBeforeUnmount(() => lifetime.abort());

async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true; emit("busy", true); error.value = "";
  try { await action(); }
  catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof ApiError && cause.status === 409 ? t("botRecovery.conflict") : cause instanceof Error ? cause.message : t("bots.failed"); }
  finally { busy.value = false; emit("busy", false); }
}
async function readHistory(page: number): Promise<void> {
  history.value = await request<BotWorkRecoveryPage | BotMessageRecoveryPage>(`${endpoint}/recoveries?${query({ q: search.value, page, page_size: historyPageSize.value })}`, "GET", undefined, { signal: lifetime.signal });
}
async function refresh(): Promise<void> {
  await perform(async () => {
    const [current] = await Promise.all([
      request<BotWorkInspection | BotMessageInspection>(endpoint, "GET", undefined, { signal: lifetime.signal }),
      readHistory(history.value.page),
    ]);
    record.value = current;
    requestKey = newRequestKey();
  });
}
async function recover(action: BotRecoveryAction): Promise<void> {
  const current = record.value;
  if (!current) return;
  const body = { request_key: requestKey, expected_revision: current.revision, action, note: note.value };
  await perform(async () => {
    if (props.kind === "work") {
      const result = await request<BotWorkRecoveryResult>(`${endpoint}/recoveries`, "POST", body, { signal: lifetime.signal });
      record.value = result.work;
    } else {
      const result = await request<BotMessageRecoveryResult>(`${endpoint}/recoveries`, "POST", body, { signal: lifetime.signal });
      record.value = result.message;
    }
    requestKey = newRequestKey(); note.value = "";
    await readHistory(1);
    emit("changed");
  });
}
onMounted(refresh);
</script>

<template>
  <section class="form-grid" data-testid="recovery-detail">
    <h3>{{ recordId }}</h3>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <button class="btn secondary" data-testid="recovery-refresh" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
    <template v-if="record">
      <p>{{ t('botRecovery.status') }}: <strong data-testid="recovery-status">{{ t(`botRecovery.states.${record.status}`) }}</strong></p>
      <p>{{ t('productCatalog.revision') }} {{ record.revision }} · {{ t('botRecovery.attempts') }} {{ record.attempts }}</p>
      <p v-if="record.error_code">{{ t('botRecovery.error') }}: <code>{{ record.error_code }}</code></p>
      <p v-if="record.retry_at">{{ t('bots.retryAt') }}: {{ new Date(record.retry_at).toLocaleString() }}</p>
      <p v-if="record.lease_until">{{ t('botRecovery.lease') }}: {{ new Date(record.lease_until).toLocaleString() }}</p>
      <RouterLink v-if="invoiceId" :to="{ path: '/invoices', query: { invoice_id: invoiceId } }">{{ t('botRecovery.invoice') }}</RouterLink>
      <p class="hint-box">{{ t(kind === 'messages' ? 'botRecovery.messageHelp' : 'botRecovery.workHelp') }}</p>
      <div v-if="record.actions.length" class="form-grid"><label class="field"><span>{{ t('botRecovery.note') }}</span><textarea v-model="note" data-testid="recovery-note" :disabled="busy" maxlength="500" /></label>
        <button v-if="record.actions.includes('retry')" class="btn" data-testid="recovery-retry" :disabled="busy" @click="recover('retry')">{{ t(kind === 'messages' ? 'botRecovery.resend' : 'botRecovery.retry') }}</button>
        <button v-if="record.actions.includes('cancel')" class="btn secondary" data-testid="recovery-cancel" :disabled="busy" @click="recover('cancel')">{{ t('botRecovery.cancel') }}</button>
      </div>
      <p v-else>{{ t('botRecovery.unavailable') }}</p>
    </template>
    <section class="form-grid" data-testid="recovery-history"><h4>{{ t('botRecovery.history') }}</h4>
      <form class="form-grid" @submit.prevent="perform(() => readHistory(1))"><label class="field"><span>{{ t('serviceSetup.search') }}</span><input v-model="search" type="search" maxlength="200" :disabled="busy" /></label><label class="field"><span>{{ t('serviceSetup.pageSize') }}</span><input v-model.number="historyPageSize" type="number" min="1" step="1" required :disabled="busy" /></label><button class="btn secondary" :disabled="busy">{{ t('serviceSetup.search') }}</button></form>
      <p>{{ t('serviceSetup.total', { count: history.count }) }}</p>
      <p v-if="!history.items.length">{{ t('serviceSetup.empty') }}</p>
      <article v-for="item in history.items" :key="item.id" class="hint-box"><p>{{ new Date(item.created_at).toLocaleString() }} · {{ t(`botRecovery.actions.${item.action}`) }} · {{ t('botRecovery.actor') }} {{ item.actor_id }}</p><p>{{ t(`botRecovery.states.${item.previous_status}`) }} · {{ t('botRecovery.attempts') }} {{ item.previous_attempts }}</p><p v-if="item.note" class="recovery-note">{{ item.note }}</p></article>
      <div class="pager"><button type="button" :disabled="busy || history.page <= 1" @click="perform(() => readHistory(history.page - 1))">‹</button><span>{{ history.page }}</span><button type="button" :disabled="busy || history.page * history.page_size >= history.count" @click="perform(() => readHistory(history.page + 1))">›</button></div>
    </section>
  </section>
</template>

<style scoped>.recovery-note { white-space: pre-wrap; overflow-wrap: anywhere; }</style>
