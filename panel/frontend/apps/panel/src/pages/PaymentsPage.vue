<script setup lang="ts">
import { useRoute } from "vue-router";
import { useAuth } from "@papilio/auth";
import { onMounted, ref, watch } from "vue";
import { item, query, request, type Page, type SmsEvent, type Topup, type SmsOriginCapabilities } from "@papilio/api";
import { asciiDigits, faDigits, faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";
import { useLocalizedFormats } from "../composables/useLocalizedFormats";
import PaymentDestinations from "../components/PaymentDestinations.vue";
import TopupEvidence from "../components/TopupEvidence.vue";
import SmsDevices from "../components/SmsDevices.vue";
import SmsObservationModal from "../components/payments/SmsObservationModal.vue";
import SmsOriginWorkspace from "../components/payments/SmsOriginWorkspace.vue";
const smsObservationId=ref<number|null>(null),smsObservationOpen=ref(false);
const smsCapabilities=ref<SmsOriginCapabilities|null>(null);
const auth = useAuth();
const { t } = useI18n();
const { date: formatDate, toman: formatToman } = useLocalizedFormats();
const route = useRoute();
const rows = ref<Topup[]>([]); const total = ref(0); const page = ref(1); const pages = ref(1); const status = ref("pending"); const selected = ref<Topup | null>(null); const bankReference = ref(""); const loading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref("");
const smsRows = ref<SmsEvent[]>([]); const smsTotal = ref(0); const smsPage = ref(1); const smsPages = ref(1); const smsLoading = ref(false);
function choose(row:Topup):void{if(busy.value)return;if(selected.value?.id!==row.id)bankReference.value="";selected.value=row;}
let listVersion=0,smsVersion=0,candidateVersion=0;
const candidates = ref<SmsEvent[]>([]); const candidatePage = ref(1); const candidatePages = ref(1); const candidateLoading = ref(false);
async function loadCandidates(): Promise<void> {
  if (!selected.value || selected.value.status !== "pending") { ++candidateVersion;candidateLoading.value=false;candidates.value = []; return; }
  const selectedId = selected.value.id;
  const version=++candidateVersion;candidateLoading.value = true;
  try { const result = await request<Page<SmsEvent>>(`/v1/admin/payments/sms/candidates/${selectedId}?${query({ page: candidatePage.value })}`); if (version!==candidateVersion||selected.value?.id !== selectedId) return; candidates.value = result.data; candidatePages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if(version===candidateVersion)error.value = cause instanceof Error ? cause.message : t("errors.request_failed"); }
  finally { if(version===candidateVersion)candidateLoading.value = false; }
}
async function loadSms(): Promise<void> {
  const version=++smsVersion;smsLoading.value = true;
  try { const result = await request<Page<SmsEvent>>(`/v1/admin/payments/sms?${query({ page: smsPage.value })}`); if(version!==smsVersion)return;smsRows.value = result.data; smsTotal.value = result.meta.pager?.total_items ?? 0; smsPages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if(version===smsVersion)error.value = cause instanceof Error ? cause.message : t("errors.request_failed"); }
  finally { if(version===smsVersion)smsLoading.value = false; }
}
async function load(): Promise<void> {
  const version=++listVersion;loading.value = true; error.value = "";
  try { const result = await request<Page<Topup>>(`/v1/admin/payments/topups?${query({ status: status.value || undefined, page: page.value })}`); if(version!==listVersion)return;rows.value = result.data; total.value = result.meta.pager?.total_items ?? 0; pages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if(version===listVersion)error.value = cause instanceof Error ? cause.message : t("errors.request_failed"); }
  finally { if(version===listVersion)loading.value = false; }
}
async function approve(): Promise<void> {
  if (!selected.value) return; busy.value = true; error.value = ""; notice.value = "";
  try { selected.value = await item<Topup>(`/v1/admin/payments/topups/${selected.value.id}/approve`, "POST", { expected_revision: selected.value.revision, bank_reference: asciiDigits(bankReference.value.trim()) }); notice.value = t("payments.approved"); bankReference.value = ""; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("errors.request_failed"); }
  finally { busy.value = false; }
}
async function reject(): Promise<void> {
  if (!selected.value) return; busy.value = true; error.value = ""; notice.value = "";
  try { selected.value = await item<Topup>(`/v1/admin/payments/topups/${selected.value.id}/reject`, "POST", { expected_revision: selected.value.revision }); notice.value = t("payments.rejected"); await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("errors.request_failed"); }
  finally { busy.value = false; }
}
watch(status, () => { page.value = 1; if(!busy.value)selected.value = null; void load() });
watch(selected, () => { candidatePage.value = 1; void loadCandidates() });
async function selectRoute(): Promise<void> {
  const id = Number(route.query.topup_id);
  if (!Number.isSafeInteger(id) || id <= 0) return;
  try { const row = await item<Topup>(`/v1/admin/payments/topups/${id}`); if (Number(route.query.topup_id) === id) choose(row); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("errors.request_failed"); }
}
watch(() => route.query.topup_id, selectRoute);
onMounted(() => { void load(); void loadSms(); void selectRoute(); });
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">{{ t('payments.eyebrow') }}</p><h1>{{ t("payments.title") }}</h1><p class="subtitle">{{ t("payments.description") }}</p></div><button class="btn secondary" @click="load(); loadSms()">{{ t('payments.refresh') }}</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div class="split"><div class="card"><div class="card-pad"><div class="toolbar"><label class="field"><span>{{ t("payments.status") }}</span><select v-model="status" :disabled="busy"><option value="pending">{{ t("payments.pending") }}</option><option value="approved">{{ t("payments.approvedStatus") }}</option><option value="rejected">{{ t("payments.rejectedStatus") }}</option><option value="">{{ t("payments.all") }}</option></select></label></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t("payments.request") }}</th><th>{{ t("payments.customer") }}</th><th>{{ t("payments.amount") }}</th><th>{{ t("payments.status") }}</th><th>{{ t("payments.bankReference") }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="choose(row)" @keydown.enter="choose(row)"><td class="tabular">{{ faNumber(row.id) }}</td><td class="tabular">{{ faNumber(row.customer_id) }}</td><td class="tabular"><strong class="tabular" dir="ltr">{{Number.isSafeInteger(row.amount_rial)?`${String(row.amount_rial)} ${t('payments.rial')}`:t('payments.amountUnavailable')}}</strong><small v-if="row.payment_identifier_code4!=null"> · {{ t('payments.identifierCode') }} {{row.payment_identifier_code4}}</small><br/><small>{{formatToman(row.amount_rial)}}</small></td><td><span class="badge" :class="row.status === 'approved' ? 'success' : row.status === 'pending' ? 'warning' : 'danger'">{{ row.status === 'approved' ? t('payments.approvedStatus') : row.status === 'pending' ? t('payments.pending') : t('payments.rejectedStatus') }}</span></td><td>{{ row.bank_reference ? faDigits(row.bank_reference) : '—' }}</td></tr></tbody></table><div v-if="!loading && !rows.length && !error" class="empty">{{ t('payments.empty') }}</div><div v-if="loading" class="empty">{{ t('payments.loading') }}</div></div><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>{{ t("payments.pageSummary", { page: faNumber(page), total: faNumber(total) }) }}</span><button :disabled="page >= pages" @click="page++; load()">›</button></div></div>
  <div class="card card-pad"><h2>{{ t("payments.review.title") }}</h2><div v-if="selected" class="form-grid"><RouterLink v-if="auth.can('support')" class="btn secondary" :to="{path:'/support',query:{customer_id:selected.customer_id,topup_id:selected.id}}">{{ t('payments.review.support') }}</RouterLink><div class="detail-line"><span>{{ t("payments.request") }} ID</span><strong>{{ faNumber(selected.id) }}</strong></div><div class="detail-line"><span>{{ t("payments.customer") }} ID</span><strong>{{ faNumber(selected.customer_id) }}</strong></div><div class="detail-line"><span>{{ t("payments.amount") }}</span><strong>{{ formatToman(selected.amount_rial) }}</strong></div><div v-if="selected.status==='approved'" class="form-grid"  :aria-label="t('payments.review.provenance')"><div class="detail-line"><span>{{ t("payments.review.approvalSource") }}</span><strong v-if="selected.approved_by_staff_id!=null">{{ t('payments.review.staff', { id: faNumber(selected.approved_by_staff_id) }) }}</strong><strong v-else-if="selected.approved_by_device_id!=null">{{ t('payments.review.device', { id: faNumber(selected.approved_by_device_id) }) }}</strong><strong v-else>{{ t('payments.notRecorded') }}</strong></div><div v-if="selected.approved_by_sms_id!=null" class="detail-line"><span>{{ t("payments.review.matchedSms") }}</span><strong>{{faNumber(selected.approved_by_sms_id)}}</strong></div></div><TopupEvidence :topup-id="selected.id" :topup="selected" audience="admin" :pending="selected.status === 'pending'" :can-upload="auth.can('payments','create')" :can-annotate="auth.can('payments','update')" /><div class="hint-box">{{ t("payments.review.manualApprovalHint") }}</div><template v-if="selected.status === 'pending' && auth.can('payments', 'create')"><label class="field"><span>{{ t("payments.review.bankTransactionReference") }}</span><input :value="faDigits(bankReference)" @input="bankReference = asciiDigits(($event.target as HTMLInputElement).value)" minlength="4" maxlength="128" /></label><div class="inline-actions"><button class="btn" :disabled="busy || bankReference.trim().length < 4" @click="approve">{{ t('payments.review.approve') }}</button><button class="btn danger" :disabled="busy" @click="reject">{{ t('payments.review.reject') }}</button></div></template><span v-else-if="selected.status !== 'pending'" class="badge" :class="selected.status === 'approved' ? 'success' : 'danger'">{{ selected.status === 'approved' ? t('payments.approvedStatus') : t('payments.rejectedStatus') }}</span></div><div v-else class="empty">{{ t("payments.review.selectRequest") }}</div></div></div>
  <PaymentDestinations :capabilities="smsCapabilities" />
  <SmsDevices :capabilities="smsCapabilities" />
  <SmsOriginWorkspace @capabilities="smsCapabilities=$event" />
  <div v-if="selected?.status === 'pending'" class="card" style="margin-top:18px"><div class="card-pad"><h2>{{ t("payments.matchingSms") }}</h2><div class="hint-box">{{ t("payments.candidatesHint") }}</div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t("payments.time") }}</th><th>{{ t("payments.sender") }}</th><th>{{ t("payments.sourceDevice") }}</th><th>{{ t("payments.amount") }}</th><th>ID</th><th></th></tr></thead><tbody><tr v-for="sms in candidates" :key="sms.id"><td>{{ formatDate(sms.sent_at) }}</td><td>{{ sms.sender }}</td><td>{{sms.device_id==null?t('payments.notRecorded'):faNumber(sms.device_id)}}</td><td>{{ sms.amount_rial === null ? t('payments.unknown') : formatToman(sms.amount_rial) }}</td><td>{{ sms.bank_reference ? faDigits(sms.bank_reference) : t('payments.unknown') }}</td><td><button v-if="smsCapabilities?.supported" class="btn small secondary" @click="smsObservationId=sms.id;smsObservationOpen=true">{{ t('payments.inspectSms') }}</button><button v-if="sms.bank_reference" class="btn small secondary" @click="bankReference = sms.bank_reference">{{ t('payments.useReference') }}</button></td></tr></tbody></table><div v-if="!candidateLoading && !candidates.length" class="empty">{{ t("payments.noMatchingSms") }}</div><div v-if="candidateLoading" class="empty">{{ t("payments.findingSms") }}</div></div><div class="pager"><button :disabled="candidatePage <= 1" @click="candidatePage--; loadCandidates()">‹</button><span>{{ t("payments.page", { page: faNumber(candidatePage) }) }}</span><button :disabled="candidatePage >= candidatePages" @click="candidatePage++; loadCandidates()">›</button></div></div>
  <div class="card" style="margin-top:18px"><div class="card-pad"><h2>{{ t("payments.incomingSms") }}</h2><div class="hint-box">{{ t("payments.incomingSmsHint") }}</div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t("payments.time") }}</th><th>{{ t("payments.sender") }}</th><th>{{ t("payments.sourceDevice") }}</th><th>{{ t("payments.parsedAmount") }}</th><th>{{ t("payments.smsReference") }}</th><th></th></tr></thead><tbody><tr v-for="sms in smsRows" :key="sms.id"><td>{{ formatDate(sms.sent_at) }}</td><td>{{ sms.sender }}</td><td>{{sms.device_id==null?t('payments.notRecorded'):faNumber(sms.device_id)}}</td><td class="tabular">{{ sms.amount_rial === null ? t('payments.unknown') : formatToman(sms.amount_rial) }}</td><td>{{ sms.bank_reference ? faDigits(sms.bank_reference) : t('payments.unknown') }}</td><td><button v-if="smsCapabilities?.supported" class="btn small secondary" @click="smsObservationId=sms.id;smsObservationOpen=true">{{ t('payments.inspectSms') }}</button><button v-if="sms.bank_reference && selected?.status === 'pending' && sms.amount_rial === selected.amount_rial" class="btn small secondary" @click="bankReference = sms.bank_reference">{{ t('payments.useReference') }}</button></td></tr></tbody></table><div v-if="!smsLoading && !smsRows.length" class="empty">{{ t("payments.noSms") }}</div><div v-if="smsLoading" class="empty">{{ t("payments.loadingSms") }}</div></div><div class="pager"><button :disabled="smsPage <= 1" @click="smsPage--; loadSms()">‹</button><span>{{ t("payments.smsPageSummary", { page: faNumber(smsPage), total: faNumber(smsTotal) }) }}</span><button :disabled="smsPage >= smsPages" @click="smsPage++; loadSms()">›</button></div></div>
  <SmsObservationModal v-model="smsObservationOpen" :event-id="smsObservationId" :capabilities="smsCapabilities"/>
</template>
