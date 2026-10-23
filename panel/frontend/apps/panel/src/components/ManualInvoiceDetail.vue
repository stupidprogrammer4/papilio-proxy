<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request, query, type CustomerAccount, type ManualInvoice, type ManualInvoiceReceipt, type ManualReceiptPage, type ManualPaymentDecision, type ManualDecisionPage, type ManualDecisionResult } from "@papilio/api";
import ManagedRecordPicker from "./ManagedRecordPicker.vue";

const props = defineProps<{ invoiceId: string; initialReceiptId?: string }>();
const emit = defineEmits<{ changed: [invoice: ManualInvoice] }>();
const { t } = useI18n();
const invoice = ref<ManualInvoice | null>(null);
const customer = ref<CustomerAccount | null>(null);
const receipts = ref<ManualReceiptPage>({ items: [], count: 0, page: 1, page_size: 20 });
const decisions = ref<ManualDecisionPage>({ items: [], count: 0, page: 1, page_size: 20 });
const selectedReceipt = ref<ManualInvoiceReceipt | null>(null);
const selectedDecision = ref<ManualPaymentDecision | null>(null);
const reference = ref(""); const note = ref(""); const reason = ref("");
const attachment = ref<File | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const busy = ref(false); const error = ref("");
const lifetime = new AbortController();
const root = `/v1/invoices/${props.invoiceId}`;
let receiptSearch = { q: "", page: 1, page_size: 20 };
let decisionSearch = { q: "", page: 1, page_size: 20 };
let receiptKey = newRequestKey(); let decisionKey = newRequestKey();
onBeforeUnmount(() => lifetime.abort());

async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); }
  catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("serviceSetup.failed"); }
  finally { busy.value = false; }
}
async function read(): Promise<void> {
  const current = await request<ManualInvoice>(root, "GET", undefined, { signal: lifetime.signal });
  const [receiptPage, decisionPage, buyer] = await Promise.all([
    request<ManualReceiptPage>(`${root}/receipts?${query(receiptSearch)}`, "GET", undefined, { signal: lifetime.signal }),
    request<ManualDecisionPage>(`${root}/decisions?${query(decisionSearch)}`, "GET", undefined, { signal: lifetime.signal }),
    request<CustomerAccount>(`/v1/customer-accounts/${current.customer_id}`, "GET", undefined, { signal: lifetime.signal }),
  ]);
  invoice.value = current; customer.value = buyer;
  receipts.value = receiptPage; decisions.value = decisionPage;
  emit("changed", current);
}
async function refresh(): Promise<void> { await perform(read); }
async function loadReceipts(search: typeof receiptSearch): Promise<void> {
  await perform(async () => { receipts.value = await request<ManualReceiptPage>(`${root}/receipts?${query(search)}`, "GET", undefined, { signal: lifetime.signal }); receiptSearch = search; });
}
async function loadDecisions(search: typeof decisionSearch): Promise<void> {
  await perform(async () => { decisions.value = await request<ManualDecisionPage>(`${root}/decisions?${query(search)}`, "GET", undefined, { signal: lifetime.signal }); decisionSearch = search; });
}
async function chooseReceipt(id: string): Promise<void> {
  await perform(async () => { selectedReceipt.value = await request<ManualInvoiceReceipt>(`${root}/receipts/${id}`, "GET", undefined, { signal: lifetime.signal }); });
}
function chooseFile(event: Event): void { attachment.value = (event.target as HTMLInputElement).files?.item(0) ?? null; }
function chooseDecision(id: string): void {
  const record = decisions.value.items.find(item => item.id === id);
  if (record) selectedDecision.value = record;
}
function newReceipt(): void {
  receiptKey = newRequestKey(); reference.value = ""; note.value = ""; attachment.value = null;
  if (fileInput.value) fileInput.value.value = "";
}
function newDecision(): void { decisionKey = newRequestKey(); reason.value = ""; }
async function submitReceipt(): Promise<void> {
  const body = new FormData();
  body.set("request_key", receiptKey); body.set("reference", reference.value); body.set("note", note.value);
  if (attachment.value) body.set("file", attachment.value);
  await perform(async () => {
    selectedReceipt.value = await request<ManualInvoiceReceipt>(`${root}/receipts`, "POST", body, { signal: lifetime.signal });
    newReceipt();
    await read();
  });
}
async function decide(action: "approve" | "reject"): Promise<void> {
  const current = invoice.value;
  if (!current) return;
  const body = { request_key: decisionKey, expected_revision: current.revision, action, reason: reason.value, receipt_id: selectedReceipt.value?.id ?? null };
  await perform(async () => {
    const result = await request<ManualDecisionResult>(`${root}/decisions`, "POST", body, { signal: lifetime.signal });
    invoice.value = result.invoice; emit("changed", result.invoice);
    newDecision();
    await read();
  });
}
onMounted(() => perform(async () => {
  const [, initialReceipt] = await Promise.all([
    read(),
    props.initialReceiptId ? request<ManualInvoiceReceipt>(`${root}/receipts/${props.initialReceiptId}`, "GET", undefined, { signal: lifetime.signal }) : Promise.resolve(null),
  ]);
  selectedReceipt.value = initialReceipt;
}));
</script>

<template>
  <section class="card card-pad form-grid" data-testid="invoice-detail">
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <button class="btn secondary" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
    <template v-if="invoice">
      <h3>{{ invoice.id }}</h3><p data-testid="invoice-customer">{{ customer?.name }}</p>
      <p data-testid="invoice-status" aria-live="polite">{{ t(`invoices.states.${invoice.status}`) }}</p>
      <p>{{ t('invoices.amountDue') }}: <span dir="ltr">{{ invoice.amount_due_minor }} {{ invoice.currency }}</span></p>
      <p>{{ t('invoices.recipient') }}: {{ invoice.settings.recipient }}</p>
      <p>{{ t('invoices.destination') }}: <span data-testid="invoice-destination" dir="ltr">{{ invoice.settings.destination }}</span></p>
      <p style="white-space: pre-wrap">{{ invoice.settings.instructions }}</p><p>{{ t('invoices.snapshotHelp') }}</p>
      <form @submit.prevent="submitReceipt"><fieldset class="form-grid" :disabled="busy || invoice.status === 'settled'">
        <legend>{{ t('invoices.submitReceipt') }}</legend>
        <button class="btn secondary" type="button" @click="newReceipt">{{ t('invoices.newReceipt') }}</button>
        <label class="field"><span>{{ t('invoices.reference') }}</span><input v-model="reference" data-testid="receipt-reference" maxlength="200" /></label>
        <label class="field"><span>{{ t('invoices.note') }}</span><textarea v-model="note" maxlength="2000" /></label>
        <label class="field"><span>{{ t('invoices.attachment', { bytes: invoice.settings.receipt_max_bytes }) }}</span><input ref="fileInput" data-testid="receipt-file" type="file" @change="chooseFile" /></label>
        <button class="btn" type="submit" data-testid="receipt-submit" :disabled="!reference.trim() && !attachment">{{ t('invoices.submitReceipt') }}</button>
      </fieldset></form>
      <ManagedRecordPicker data-testid="receipt-picker" :title="t('invoices.receipts')" :items="receipts.items.map(item => ({ id: item.id, label: item.reference || item.filename }))" :count="receipts.count" :page="receipts.page" :page-size="receipts.page_size" :selected-id="selectedReceipt?.id" :busy="busy" @search="loadReceipts" @select="chooseReceipt" />
      <div v-if="selectedReceipt" class="form-grid">
        <p>{{ selectedReceipt.reference }}</p><p style="white-space: pre-wrap">{{ selectedReceipt.note }}</p>
        <a v-if="selectedReceipt.size_bytes" class="btn secondary" data-testid="receipt-download" :href="`/api${root}/receipts/${selectedReceipt.id}/file`" download>{{ t('invoices.download') }}: {{ selectedReceipt.filename }}</a>
        <button class="btn secondary" :disabled="busy" @click="selectedReceipt = null">{{ t('invoices.clearReceipt') }}</button>
      </div>
      <form @submit.prevent="decide('approve')"><fieldset class="form-grid" :disabled="busy || invoice.status === 'settled'">
        <legend>{{ t('invoices.reviewTitle') }}</legend><p>{{ t('invoices.reviewHelp') }}</p>
        <button class="btn secondary" type="button" @click="newDecision">{{ t('invoices.newDecision') }}</button>
        <label class="field"><span>{{ t('invoices.reason') }}</span><textarea v-model="reason" data-testid="payment-decision-reason" required maxlength="500" /></label>
        <button class="btn" type="submit" data-testid="payment-approve" :disabled="!reason.trim()">{{ t('invoices.approve') }}</button>
        <button class="btn secondary" type="button" :disabled="!reason.trim()" @click="decide('reject')">{{ t('invoices.reject') }}</button>
      </fieldset></form>
      <ManagedRecordPicker :title="t('invoices.decisions')" :items="decisions.items.map(item => ({ id: item.id, label: `${t(`invoices.actions.${item.action}`)} · ${item.reason}` }))" :count="decisions.count" :page="decisions.page" :page-size="decisions.page_size" :selected-id="selectedDecision?.id" :busy="busy" @search="loadDecisions" @select="chooseDecision" />
      <p v-if="selectedDecision">{{ t(`invoices.actions.${selectedDecision.action}`) }} · {{ selectedDecision.reason }} · <time :datetime="selectedDecision.created_at">{{ selectedDecision.created_at }}</time></p>
    </template>
  </section>
</template>
