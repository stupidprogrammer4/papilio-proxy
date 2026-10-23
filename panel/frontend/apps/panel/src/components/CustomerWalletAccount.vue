<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, ApiError, type CustomerAccount, type CustomerWallet, type WalletJournalEntry, type WalletJournalPage, type WalletJournalPost } from "@papilio/api";
import ManagedRecordPicker from "./ManagedRecordPicker.vue";

const props = defineProps<{ customer: CustomerAccount }>();
const { t } = useI18n();
const wallet = ref<CustomerWallet | null>(null);
const journal = ref<WalletJournalPage>({ items: [], count: 0, page: 1, page_size: 20 });
const selected = ref<WalletJournalEntry | null>(null);
const creditLimit = ref("0");
const kind = ref<WalletJournalPost["kind"]>("credit");
const amount = ref("");
const reason = ref("");
const ready = ref(false);
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
const path = `/v1/customer-accounts/${props.customer.id}/wallet`;
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
async function readWallet(): Promise<void> {
  try {
    wallet.value = await request<CustomerWallet>(path, "GET", undefined, { signal: lifetime.signal });
    creditLimit.value = wallet.value.credit_limit_minor;
  } catch (cause) {
    if (!(cause instanceof ApiError && cause.status === 404)) throw cause;
    wallet.value = null;
  }
  ready.value = true;
}
async function load(search: { q: string; page: number; page_size: number }): Promise<void> {
  await perform(async () => {
    journal.value = await request<WalletJournalPage>(`${path}/entries?${query(search)}`, "GET", undefined, { signal: lifetime.signal });
    currentSearch = search;
  });
}
async function refresh(): Promise<void> {
  await perform(async () => {
    await readWallet();
    if (wallet.value) journal.value = await request<WalletJournalPage>(`${path}/entries?${query(currentSearch)}`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function open(): Promise<void> {
  await perform(async () => {
    wallet.value = await request<CustomerWallet>(path, "POST", { currency: "IRR", credit_limit_minor: creditLimit.value }, { signal: lifetime.signal });
    journal.value = await request<WalletJournalPage>(`${path}/entries`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function saveLimit(): Promise<void> {
  const current = wallet.value;
  if (!current) return;
  await perform(async () => {
    wallet.value = await request<CustomerWallet>(path, "PUT", { expected_revision: current.revision, credit_limit_minor: creditLimit.value }, { signal: lifetime.signal });
  });
}
async function post(): Promise<void> {
  const input: WalletJournalPost = { request_key: requestKey, kind: kind.value, amount_minor: amount.value, reason: reason.value };
  await perform(async () => {
    selected.value = await request<WalletJournalEntry>(`${path}/entries`, "POST", input, { signal: lifetime.signal });
    requestKey = newRequestKey();
    amount.value = "";
    reason.value = "";
    await readWallet();
    journal.value = await request<WalletJournalPage>(`${path}/entries?${query(currentSearch)}`, "GET", undefined, { signal: lifetime.signal });
  });
}
async function select(id: string): Promise<void> {
  await perform(async () => {
    selected.value = await request<WalletJournalEntry>(`${path}/entries/${id}`, "GET", undefined, { signal: lifetime.signal });
  });
}
onMounted(refresh);
</script>

<template>
  <section class="card card-pad form-grid">
    <h3>{{ t('sales.wallet') }}</h3>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <button class="btn secondary" data-testid="wallet-refresh" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
    <p v-if="ready && !wallet">{{ t('sales.noWallet') }}</p>
    <template v-if="wallet">
      <p data-testid="wallet-balance" aria-live="polite" dir="ltr">{{ wallet.balance_minor }} {{ wallet.currency }} ({{ wallet.unit }})</p>
      <p data-testid="wallet-limit-current">{{ t('sales.creditLimit') }}: {{ wallet.credit_limit_minor }} IRR</p>
    </template>
    <form v-if="ready" @submit.prevent="wallet ? saveLimit() : open()"><fieldset class="form-grid" :disabled="busy">
      <label class="field"><span>{{ t('sales.creditLimit') }}</span><input v-model="creditLimit" data-testid="wallet-credit-limit" type="text" inputmode="numeric" pattern="[0-9]+" required maxlength="19" dir="ltr" /></label>
      <p>{{ t('sales.creditHelp') }}</p>
      <button v-if="!wallet" class="btn" data-testid="wallet-open" type="submit">{{ t('sales.openWallet') }}</button>
      <button v-else class="btn secondary" data-testid="wallet-save-limit" type="submit">{{ t('sales.saveLimit') }}</button>
    </fieldset></form>
    <form v-if="wallet" @submit.prevent="post"><fieldset class="form-grid" :disabled="busy">
      <h3>{{ t('sales.adjustment') }}</h3><p>{{ t('sales.adjustmentHelp') }}</p>
      <label class="field"><span>{{ t('sales.kind') }}</span><select v-model="kind" data-testid="wallet-kind"><option value="credit">{{ t('sales.credit') }}</option><option value="debit">{{ t('sales.debit') }}</option></select></label>
      <label class="field"><span>{{ t('sales.amount') }}</span><input v-model="amount" data-testid="wallet-amount" type="text" inputmode="numeric" pattern="[0-9]+" required maxlength="19" dir="ltr" /></label>
      <label class="field"><span>{{ t('sales.reason') }}</span><input v-model="reason" data-testid="wallet-reason" required maxlength="500" /></label>
      <button class="btn" type="submit" data-testid="wallet-post">{{ t('sales.post') }}</button>
    </fieldset></form>
    <ManagedRecordPicker v-if="wallet" data-testid="wallet-journal" :title="t('sales.journal')" :items="journal.items.map(item => ({ id: item.id, label: `${t(`sales.${item.kind}`)} ${item.amount_minor} IRR · ${item.reason}` }))" :count="journal.count" :page="journal.page" :page-size="journal.page_size" :selected-id="selected?.id" :busy="busy" @search="load" @select="select" />
    <section v-if="selected" class="form-grid" data-testid="wallet-entry">
      <h3>{{ selected.reason }}</h3>
      <p>{{ t('sales.before') }}: <span dir="ltr">{{ selected.balance_before_minor }} IRR</span></p>
      <p>{{ t('sales.after') }}: <span dir="ltr">{{ selected.balance_after_minor }} IRR</span></p>
      <time :datetime="selected.created_at">{{ new Date(selected.created_at).toLocaleString() }}</time>
    </section>
  </section>
</template>
