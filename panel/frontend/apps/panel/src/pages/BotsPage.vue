<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type BotDefaults, type BotDraft, type BotPairingGrant, type ManagedBot, type ManagedBotPage } from "@papilio/api";
import BotConnectionEditor from "../components/bot/BotConnectionEditor.vue";

const { t } = useI18n();
const rows = ref<ManagedBot[]>([]);
const selected = ref<ManagedBot | null>(null);
const creation = ref<BotDraft | null>(null);
const editing = ref<BotDraft | null>(null);
const editRevision = ref<string | null>(null);
const pairing = ref<BotPairingGrant | null>(null);
const search = ref("");
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const lifetime = new AbortController();
let requestKey = crypto.randomUUID();
onBeforeUnmount(() => lifetime.abort());

function edit(bot: ManagedBot): void {
  editing.value = { label: bot.label, token: "", runtime: { ...bot.runtime }, schedule: { ...bot.schedule } };
  editRevision.value = bot.revision;
  pairing.value = null;
}

async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try { await action(); }
  catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("bots.failed"); }
  finally { busy.value = false; }
}

async function loadRows(): Promise<void> {
  const result = await request<ManagedBotPage>(`/v1/bots?${query({ q: search.value, page: page.value, page_size: pageSize })}`, "GET", undefined, { signal: lifetime.signal });
  rows.value = result.items;
  total.value = result.count;
}

async function refresh(): Promise<void> {
  await perform(async () => {
    await loadRows();
    if (selected.value) selected.value = await request<ManagedBot>(`/v1/bots/${selected.value.id}`, "GET", undefined, { signal: lifetime.signal });
  });
}

async function select(bot: ManagedBot): Promise<void> {
  await perform(async () => {
    selected.value = await request<ManagedBot>(`/v1/bots/${bot.id}`, "GET", undefined, { signal: lifetime.signal });
    edit(selected.value);
  });
}

async function create(): Promise<void> {
  const draft = creation.value;
  if (!draft) return;
  await perform(async () => {
    const result = await request<ManagedBot>("/v1/bots", "POST", { ...draft, request_key: requestKey }, { signal: lifetime.signal });
    requestKey = crypto.randomUUID();
    selected.value = result;
    edit(result);
    draft.token = "";
    draft.label = "";
    notice.value = t('bots.created');
    await loadRows();
  });
}

async function save(): Promise<void> {
  const bot = selected.value, draft = editing.value;
  if (!bot || !draft || editRevision.value === null) return;
  await perform(async () => {
    const result = await request<ManagedBot>(`/v1/bots/${bot.id}`, "PUT", { label: draft.label, runtime: draft.runtime, schedule: draft.schedule, expected_revision: editRevision.value, ...(draft.token ? { token: draft.token } : {}) }, { signal: lifetime.signal });
    selected.value = result;
    edit(result);
    notice.value = t('bots.saved');
    await loadRows();
  });
}

async function pair(): Promise<void> {
  const bot = selected.value;
  if (!bot) return;
  await perform(async () => {
    pairing.value = await request<BotPairingGrant>(`/v1/bots/${bot.id}/pairing`, "POST", undefined, { signal: lifetime.signal });
  });
}
async function find(): Promise<void> { page.value = 1; await refresh(); }
async function turn(delta: number): Promise<void> { page.value += delta; await refresh(); }
onMounted(async () => {
  await perform(async () => {
    const defaults = await request<BotDefaults>("/v1/bots/defaults", "GET", undefined, { signal: lifetime.signal });
    creation.value = { label: "", token: "", ...defaults };
    await loadRows();
  });
});
</script>

<template>
  <div class="stack">
    <header class="page-heading"><h1>{{ t('bots.title') }}</h1><p>{{ t('bots.help') }}</p></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message" role="status">{{ notice }}</p>
    <button class="btn secondary" data-testid="bot-refresh" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
    <section class="card card-pad form-grid"><h2>{{ t('bots.create') }}</h2>
      <form v-if="creation" class="form-grid" @submit.prevent="create"><BotConnectionEditor v-model="creation" :disabled="busy" :token-required="true" test-prefix="bot-create" /><button class="btn" data-testid="bot-create-submit" :disabled="busy">{{ t('bots.create') }}</button></form>
    </section>
    <section class="card card-pad form-grid">
      <form class="form-grid" @submit.prevent="find"><label class="field"><span>{{ t('bots.search') }}</span><input v-model="search" data-testid="bot-search" maxlength="200" :disabled="busy" /></label><button class="btn secondary" :disabled="busy">{{ t('bots.search') }}</button></form>
      <p>{{ t('bots.total', { count: total }) }}</p>
      <div class="table-wrap" data-testid="bot-list"><table class="data-table"><thead><tr><th>{{ t('bots.label') }}</th><th>{{ t('bots.identity') }}</th><th>{{ t('bots.schedule') }}</th></tr></thead><tbody><tr v-for="bot in rows" :key="bot.id"><td><button class="btn secondary" data-testid="bot-row" :disabled="busy" @click="select(bot)">{{ bot.label }}</button></td><td>{{ bot.username ? `@${bot.username}` : t('bots.unverified') }}</td><td>{{ t(bot.schedule.enabled ? 'bots.enabled' : 'bots.disabled') }}</td></tr></tbody></table></div>
      <div class="pager"><button :disabled="busy || page <= 1" @click="turn(-1)">‹</button><span>{{ page }}</span><button :disabled="busy || page * pageSize >= total" @click="turn(1)">›</button></div>
    </section>
    <section v-if="selected" class="card card-pad form-grid" data-testid="bot-detail">
      <h2>{{ selected.label }}</h2>
      <p>{{ t('bots.identity') }}: {{ selected.username ? `@${selected.username}` : '—' }} · {{ t(selected.verified ? 'bots.verified' : 'bots.unverified') }}</p>
      <p>{{ t('bots.adminChat') }}: {{ selected.admin_chat_id ?? t('bots.unpaired') }}</p>
      <p v-if="selected.retry_at">{{ t('bots.retryAt') }}: {{ new Date(selected.retry_at).toLocaleString() }}</p>
      <p v-if="selected.last_poll_at">{{ t('foundation.observed') }}: {{ new Date(selected.last_poll_at).toLocaleString() }}</p>
      <p v-if="selected.last_error_code" class="message error" role="alert">{{ t(`bots.errors.${selected.last_error_code}`) }}</p>
      <button class="btn" data-testid="bot-pair-create" :disabled="busy || !selected.verified || !selected.schedule.enabled" @click="pair">{{ t('bots.pair') }}</button>
      <div v-if="pairing" class="hint-box"><p>{{ t('bots.pairHelp') }}</p><a :href="pairing.url" data-testid="bot-pair-link" target="_blank" rel="noopener noreferrer">{{ t('bots.openTelegram') }}</a><p>{{ t('bots.expires') }}: {{ new Date(pairing.expires_at).toLocaleString() }}</p></div>
      <form v-if="editing" class="form-grid" @submit.prevent="save"><h3>{{ t('bots.edit') }}</h3><p>{{ t('bots.saveHelp') }}</p><BotConnectionEditor v-model="editing" :disabled="busy" :token-required="false" test-prefix="bot-edit" /><button class="btn" data-testid="bot-edit-submit" :disabled="busy">{{ t('foundation.save') }}</button><button class="btn secondary" type="button" :disabled="busy" @click="select(selected)">{{ t('bots.reload') }}</button></form>
      <p class="hint-box">{{ t('bots.scope') }}</p>
    </section>
  </div>
</template>
