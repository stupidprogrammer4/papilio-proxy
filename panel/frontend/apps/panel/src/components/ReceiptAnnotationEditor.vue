<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { item, query, request, type Page, type PaymentReceipt, type ReceiptAnnotation, type ReceiptAnnotationWrite } from "@papilio/api";
import { asciiDigits } from "@papilio/ui";
import { useI18n } from "vue-i18n";

const props = defineProps<{ topupId: number; receiptId: number; extraction: PaymentReceipt["extraction"] }>();
const { locale, t } = useI18n();
const history = ref<ReceiptAnnotation[]>([]);
const historyPage = ref(1);
const historyPages = ref(1);
const expectedRevision = ref(0);
const expanded = ref(false);
const loading = ref(false);
const loaded = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const draft = reactive({ amount: "", currency: "rial" as "rial" | "toman", destinationKind: "" as "" | "card" | "iban" | "account", destination: "", bank: "", reference: "", occurredAt: "", status: "", reason: "" });
const path = () => `/v1/admin/payments/topups/${props.topupId}/receipts/${props.receiptId}/annotations`;

function localDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

function annotationDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function fill(annotation: ReceiptAnnotation | undefined): void {
  const fields = annotation?.fields ?? props.extraction;
  draft.amount = fields?.amount_rial?.toString() ?? "";
  draft.currency = fields?.currency ?? "rial";
  draft.destinationKind = fields?.destination_kind ?? "";
  draft.destination = fields?.visible_destination ?? "";
  draft.bank = fields?.bank_namespace ?? "";
  draft.reference = fields?.bank_reference ?? "";
  draft.occurredAt = localDateTime(fields?.occurred_at_utc);
  draft.status = fields?.transaction_status_claim ?? "";
  draft.reason = "";
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await request<Page<ReceiptAnnotation>>(`${path()}?${query({ page: historyPage.value, per_page: 50 })}`);
    history.value = result.data;
    historyPages.value = result.meta.pager?.total_pages ?? 1;
    if (historyPage.value === 1) {
      expectedRevision.value = history.value[0]?.revision ?? 0;
      fill(history.value[0]);
    }
    loaded.value = true;
  } catch (cause) {
    loaded.value = false;
    error.value = cause instanceof Error ? cause.message : t("errors.request_failed");
  } finally {
    loading.value = false;
  }
}

function toggle(): void {
  expanded.value = !expanded.value;
  if (expanded.value && !loaded.value && !loading.value) void load();
}

async function save(): Promise<void> {
  busy.value = true;
  error.value = "";
  notice.value = "";
  const amountText = asciiDigits(draft.amount.trim());
  const amount = amountText === "" ? null : Number(amountText);
  if (amount !== null && (!Number.isSafeInteger(amount) || amount < 0)) {
    error.value = t("payments.evidence.annotationAmountInvalid");
    busy.value = false;
    return;
  }
  const data: ReceiptAnnotationWrite = {
    expected_revision: expectedRevision.value,
    fields: {
      amount_rial: amount,
      currency: amount === null ? null : draft.currency,
      destination_kind: draft.destinationKind || null,
      visible_destination: draft.destination.trim() || null,
      bank_namespace: draft.bank.trim() || null,
      bank_reference: draft.reference.trim() || null,
      occurred_at_utc: draft.occurredAt ? new Date(draft.occurredAt).toISOString() : null,
      transaction_status_claim: draft.status.trim() || null,
    },
    reason: draft.reason.trim(),
  };
  try {
    await item<ReceiptAnnotation>(path(), "PUT", data);
    notice.value = t("payments.evidence.annotationSaved");
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("errors.request_failed");
  } finally {
    busy.value = false;
  }
}

watch(() => [props.topupId, props.receiptId], () => { historyPage.value = 1; loaded.value = false; expanded.value = false; history.value = []; fill(undefined); });
</script>

<template>
  <section class="form-grid" :aria-label="t('payments.evidence.annotationTitle')">
    <button type="button" class="btn secondary" :aria-expanded="expanded" @click="toggle">{{ t("payments.evidence.annotationTitle") }}</button>
    <div v-if="expanded" class="form-grid">
    <p>{{ t("payments.evidence.annotationExplanation") }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }} <button class="btn small secondary" :disabled="loading" @click="load">{{ t("payments.evidence.retry") }}</button></p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="loading">{{ t("payments.evidence.annotationLoading") }}</p>
    <ol v-if="history.length" :aria-label="t('payments.evidence.annotationHistory')">
      <li v-for="row in history" :key="row.id" class="form-grid">
        <strong>{{ t("payments.evidence.annotationRevision", { revision: row.revision, staff: row.staff_id }) }}</strong>
        <time :datetime="row.created_at">{{ annotationDate(row.created_at) }}</time>
        <p>{{ t("payments.evidence.annotationReason") }}: {{ row.reason }}</p>
        <dl class="grid two">
          <div v-if="row.fields.amount_rial !== null"><dt>{{ t("payments.evidence.ocrAmount") }}</dt><dd>{{ row.fields.amount_rial }} RIAL</dd></div>
          <div v-if="row.fields.currency"><dt>{{ t("payments.evidence.currencyLabel") }}</dt><dd>{{ t(`payments.evidence.currency.${row.fields.currency}`) }}</dd></div>
          <div v-if="row.fields.destination_kind"><dt>{{ t("payments.evidence.destinationKind") }}</dt><dd>{{ t(`payments.evidence.kind.${row.fields.destination_kind}`) }}</dd></div>
          <div v-if="row.fields.visible_destination"><dt>{{ t("payments.evidence.ocrDestination") }}</dt><dd dir="ltr">{{ row.fields.visible_destination }}</dd></div>
          <div v-if="row.fields.bank_namespace"><dt>{{ t("payments.evidence.ocrBank") }}</dt><dd>{{ row.fields.bank_namespace }}</dd></div>
          <div v-if="row.fields.bank_reference"><dt>{{ t("payments.evidence.ocrReference") }}</dt><dd dir="ltr">{{ row.fields.bank_reference }}</dd></div>
          <div v-if="row.fields.occurred_at_utc"><dt>{{ t("payments.evidence.annotationTime") }}</dt><dd>{{ row.fields.occurred_at_utc }}</dd></div>
          <div v-if="row.fields.transaction_status_claim"><dt>{{ t("payments.evidence.ocrStatusClaim") }}</dt><dd>{{ row.fields.transaction_status_claim }}</dd></div>
        </dl>
      </li>
    </ol>
    <div v-if="historyPages > 1" class="pager">
      <button :disabled="loading || historyPage <= 1" @click="historyPage--; load()">{{ t("payments.evidence.annotationPrevious") }}</button>
      <span>{{ historyPage }} / {{ historyPages }}</span>
      <button :disabled="loading || historyPage >= historyPages" @click="historyPage++; load()">{{ t("payments.evidence.annotationNext") }}</button>
    </div>
    <form class="form-grid" @submit.prevent="save">
      <div class="grid two">
        <label class="field"><span>{{ t("payments.evidence.ocrAmount") }} · RIAL</span><input v-model="draft.amount" inputmode="numeric" /></label>
        <label class="field"><span>{{ t("payments.evidence.currencyLabel") }}</span><select v-model="draft.currency"><option value="rial">{{ t("payments.evidence.currency.rial") }}</option><option value="toman">{{ t("payments.evidence.currency.toman") }}</option></select></label>
        <label class="field"><span>{{ t("payments.evidence.destinationKind") }}</span><select v-model="draft.destinationKind"><option value="">—</option><option value="card">{{ t("payments.evidence.kind.card") }}</option><option value="iban">{{ t("payments.evidence.kind.iban") }}</option><option value="account">{{ t("payments.evidence.kind.account") }}</option></select></label>
        <label class="field"><span>{{ t("payments.evidence.ocrDestination") }}</span><input v-model="draft.destination" /></label>
        <label class="field"><span>{{ t("payments.evidence.ocrBank") }}</span><input v-model="draft.bank" /></label>
        <label class="field"><span>{{ t("payments.evidence.ocrReference") }}</span><input v-model="draft.reference" dir="ltr" /></label>
        <label class="field"><span>{{ t("payments.evidence.annotationTime") }}</span><input v-model="draft.occurredAt" type="datetime-local" /></label>
        <label class="field"><span>{{ t("payments.evidence.ocrStatusClaim") }}</span><input v-model="draft.status" /></label>
      </div>
      <label class="field"><span>{{ t("payments.evidence.annotationReason") }}</span><textarea v-model="draft.reason" required maxlength="250" rows="2" /></label>
      <button class="btn" :disabled="busy || loading || !loaded || historyPage !== 1 || !draft.reason.trim()">{{ t("payments.evidence.annotationSave") }}</button>
    </form>
    </div>
  </section>
</template>
