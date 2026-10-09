<script setup lang="ts">
import { useRoute } from "vue-router";
import { useAuth } from "@papilio/auth";
import { onMounted, ref, watch } from "vue";
import { item, query, request, type Page, type SmsEvent, type Topup, type SmsOriginCapabilities } from "@papilio/api";
import { asciiDigits, faDate, faDigits, faNumber, toman } from "@papilio/ui";
import PaymentDestinations from "../components/PaymentDestinations.vue";
import TopupEvidence from "../components/TopupEvidence.vue";
import SmsDevices from "../components/SmsDevices.vue";
import SmsObservationModal from "../components/payments/SmsObservationModal.vue";
import SmsOriginWorkspace from "../components/payments/SmsOriginWorkspace.vue";
const smsObservationId=ref<number|null>(null),smsObservationOpen=ref(false);
const smsCapabilities=ref<SmsOriginCapabilities|null>(null);
const auth = useAuth();
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
  catch (cause) { if(version===candidateVersion)error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if(version===candidateVersion)candidateLoading.value = false; }
}
async function loadSms(): Promise<void> {
  const version=++smsVersion;smsLoading.value = true;
  try { const result = await request<Page<SmsEvent>>(`/v1/admin/payments/sms?${query({ page: smsPage.value })}`); if(version!==smsVersion)return;smsRows.value = result.data; smsTotal.value = result.meta.pager?.total_items ?? 0; smsPages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if(version===smsVersion)error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if(version===smsVersion)smsLoading.value = false; }
}
async function load(): Promise<void> {
  const version=++listVersion;loading.value = true; error.value = "";
  try { const result = await request<Page<Topup>>(`/v1/admin/payments/topups?${query({ status: status.value || undefined, page: page.value })}`); if(version!==listVersion)return;rows.value = result.data; total.value = result.meta.pager?.total_items ?? 0; pages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if(version===listVersion)error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if(version===listVersion)loading.value = false; }
}
async function approve(): Promise<void> {
  if (!selected.value) return; busy.value = true; error.value = ""; notice.value = "";
  try { selected.value = await item<Topup>(`/v1/admin/payments/topups/${selected.value.id}/approve`, "POST", { bank_reference: asciiDigits(bankReference.value.trim()) }); notice.value = "Payment approved. The customer wallet has been credited."; bankReference.value = ""; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function reject(): Promise<void> {
  if (!selected.value) return; busy.value = true; error.value = ""; notice.value = "";
  try { selected.value = await item<Topup>(`/v1/admin/payments/topups/${selected.value.id}/reject`, "POST"); notice.value = "Request rejected. The wallet was unchanged."; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
watch(status, () => { page.value = 1; if(!busy.value)selected.value = null; void load() });
watch(selected, () => { candidatePage.value = 1; void loadCandidates() });
async function selectRoute(): Promise<void> {
  const id = Number(route.query.topup_id);
  if (!Number.isSafeInteger(id) || id <= 0) return;
  try { const row = await item<Topup>(`/v1/admin/payments/topups/${id}`); if (Number(route.query.topup_id) === id) choose(row); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
watch(() => route.query.topup_id, selectRoute);
onMounted(() => { void load(); void loadSms(); void selectRoute(); });
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">PAYMENT RECONCILIATION</p><h1>Payments</h1><p class="subtitle">Review wallet top-ups, bank references and incoming SMS matches.</p></div><button class="btn secondary" @click="load(); loadSms()">Refresh</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div class="split"><div class="card"><div class="card-pad"><div class="toolbar"><label class="field"><span>Request status</span><select v-model="status" :disabled="busy"><option value="pending">Pending review</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="">All</option></select></label></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Request</th><th>Customer</th><th>Amount</th><th>Status</th><th>Bank reference</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="choose(row)" @keydown.enter="choose(row)"><td class="tabular">{{ faNumber(row.id) }}</td><td class="tabular">{{ faNumber(row.customer_id) }}</td><td class="tabular"><strong class="tabular" dir="ltr">{{Number.isSafeInteger(row.amount_rial)?String(row.amount_rial)+' RIAL':'Exact amount unavailable'}}</strong><small v-if="row.payment_identifier_code4!=null"> · Code {{row.payment_identifier_code4}}</small><br/><small>{{toman(row.amount_rial)}}</small></td><td><span class="badge" :class="row.status === 'approved' ? 'success' : row.status === 'pending' ? 'warning' : 'danger'">{{ row.status === 'approved' ? 'Approved' : row.status === 'pending' ? 'Pending review' : 'Rejected' }}</span></td><td>{{ row.bank_reference ? faDigits(row.bank_reference) : '—' }}</td></tr></tbody></table><div v-if="!loading && !rows.length && !error" class="empty">No payment requests match this status.</div><div v-if="loading" class="empty">Loading payments…</div></div><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} Request</span><button :disabled="page >= pages" @click="page++; load()">›</button></div></div>
  <div class="card card-pad"><h2>Payment review</h2><div v-if="selected" class="form-grid"><RouterLink v-if="auth.can('support')" class="btn secondary" :to="{path:'/support',query:{customer_id:selected.customer_id,topup_id:selected.id}}">Payment support</RouterLink><div class="detail-line"><span>Request ID</span><strong>{{ faNumber(selected.id) }}</strong></div><div class="detail-line"><span>Customer ID</span><strong>{{ faNumber(selected.customer_id) }}</strong></div><div class="detail-line"><span>Amount</span><strong>{{ toman(selected.amount_rial) }}</strong></div><div v-if="selected.status==='approved'" class="form-grid" aria-label="Payment approval provenance"><div class="detail-line"><span>Approval source</span><strong v-if="selected.approved_by_staff_id!=null">Staff {{faNumber(selected.approved_by_staff_id)}}</strong><strong v-else-if="selected.approved_by_device_id!=null">Enrolled SMS device {{faNumber(selected.approved_by_device_id)}}</strong><strong v-else>Not recorded</strong></div><div v-if="selected.approved_by_sms_id!=null" class="detail-line"><span>Matched SMS record</span><strong>{{faNumber(selected.approved_by_sms_id)}}</strong></div></div><TopupEvidence :topup-id="selected.id" :topup="selected" audience="admin" :pending="selected.status === 'pending'" :can-upload="auth.can('payments','create')" /><div class="hint-box">Check bank settlement before manual approval. Each bank reference can credit one request. Trusted enrolled-device SMS follows the configured matching policy; ambiguous matches require review.</div><template v-if="selected.status === 'pending' && auth.can('payments', 'create')"><label class="field"><span>Bank transaction reference</span><input :value="faDigits(bankReference)" @input="bankReference = asciiDigits(($event.target as HTMLInputElement).value)" minlength="4" maxlength="128" /></label><div class="inline-actions"><button class="btn" :disabled="busy || bankReference.trim().length < 4" @click="approve">Approve and credit wallet</button><button class="btn danger" :disabled="busy" @click="reject">Reject request</button></div></template><span v-else-if="selected.status !== 'pending'" class="badge" :class="selected.status === 'approved' ? 'success' : 'danger'">{{ selected.status === 'approved' ? 'Approved' : 'Rejected' }}</span></div><div v-else class="empty">Select a payment request to review its details.</div></div></div>
  <PaymentDestinations :capabilities="smsCapabilities" />
  <SmsDevices :capabilities="smsCapabilities" />
  <SmsOriginWorkspace @capabilities="smsCapabilities=$event" />
  <div v-if="selected?.status === 'pending'" class="card" style="margin-top:18px"><div class="card-pad"><h2>Matching SMS</h2><div class="hint-box">These SMS records match the amount and configured time window. Review ambiguous matches and confirm the correct request before approving manually.</div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Sender</th><th>Source device</th><th>Amount</th><th>ID</th><th></th></tr></thead><tbody><tr v-for="sms in candidates" :key="sms.id"><td>{{ faDate(sms.sent_at) }}</td><td>{{ sms.sender }}</td><td>{{sms.device_id==null?'Not recorded':faNumber(sms.device_id)}}</td><td>{{ sms.amount_rial === null ? 'Unknown' : toman(sms.amount_rial) }}</td><td>{{ sms.bank_reference ? faDigits(sms.bank_reference) : 'Unknown' }}</td><td><button v-if="smsCapabilities?.supported" class="btn small secondary" @click="smsObservationId=sms.id;smsObservationOpen=true">Inspect SMS</button><button v-if="sms.bank_reference" class="btn small secondary" @click="bankReference = sms.bank_reference">Use reference</button></td></tr></tbody></table><div v-if="!candidateLoading && !candidates.length" class="empty">No matching SMS found. Enter the bank reference after checking settlement.</div><div v-if="candidateLoading" class="empty">Finding SMS matches…</div></div><div class="pager"><button :disabled="candidatePage <= 1" @click="candidatePage--; loadCandidates()">‹</button><span>Page {{ faNumber(candidatePage) }}</span><button :disabled="candidatePage >= candidatePages" @click="candidatePage++; loadCandidates()">›</button></div></div>
  <div class="card" style="margin-top:18px"><div class="card-pad"><h2>Incoming bank SMS</h2><div class="hint-box">Review parsed amounts and references against customer requests. Automatic approval requires an enrolled device and an unambiguous match under the configured policy.</div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Sender</th><th>Source device</th><th>Parsed amount</th><th>SMS reference</th><th></th></tr></thead><tbody><tr v-for="sms in smsRows" :key="sms.id"><td>{{ faDate(sms.sent_at) }}</td><td>{{ sms.sender }}</td><td>{{sms.device_id==null?'Not recorded':faNumber(sms.device_id)}}</td><td class="tabular">{{ sms.amount_rial === null ? 'Unknown' : toman(sms.amount_rial) }}</td><td>{{ sms.bank_reference ? faDigits(sms.bank_reference) : 'Unknown' }}</td><td><button v-if="smsCapabilities?.supported" class="btn small secondary" @click="smsObservationId=sms.id;smsObservationOpen=true">Inspect SMS</button><button v-if="sms.bank_reference && selected?.status === 'pending' && sms.amount_rial === selected.amount_rial" class="btn small secondary" @click="bankReference = sms.bank_reference">Use reference</button></td></tr></tbody></table><div v-if="!smsLoading && !smsRows.length" class="empty">No SMS received yet.</div><div v-if="smsLoading" class="empty">Loading SMS…</div></div><div class="pager"><button :disabled="smsPage <= 1" @click="smsPage--; loadSms()">‹</button><span>Page {{ faNumber(smsPage) }} · {{ faNumber(smsTotal) }} SMS</span><button :disabled="smsPage >= smsPages" @click="smsPage++; loadSms()">›</button></div></div>
  <SmsObservationModal v-model="smsObservationOpen" :event-id="smsObservationId" :capabilities="smsCapabilities"/>
</template>
