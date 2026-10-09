<script setup lang="ts">
import { useRoute } from "vue-router";
import CustomerPicker from "../components/CustomerPicker.vue";
import IpPolicySummary from "../components/IpPolicySummary.vue";
import SubscriptionControl from "../components/SubscriptionControl.vue";
import UsageRecords from "../components/UsageRecords.vue";
import SubscriptionProvisioning from "../components/SubscriptionProvisioning.vue";
import SubscriptionIpLimit from "../components/SubscriptionIpLimit.vue";
import { useAuth } from "@papilio/auth";
import { computed, onMounted, ref, watch } from "vue";
import { item, query, request, type Page, type Subscription } from "@papilio/api";
import { faDate, faNumber, toman } from "@papilio/ui";
const auth = useAuth();
const route = useRoute();
const rows = ref<Subscription[]>([]); const total = ref(0); const page = ref(1); const pages = ref(1); const status = ref(""); const customerId = ref(String(route.query.customer_id ?? "")); const selected = ref<Subscription | null>(null); const reason = ref(""); const loading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref("");
const customerChoice = computed({ get: () => { const id=Number(customerId.value); return Number.isSafeInteger(id)&&id>0?id:null; }, set: (id:number|null) => { customerId.value=id===null?"":String(id); } });
const parentLocked = computed(() => route.query.customer_id !== undefined);
let listVersion=0;
function choose(row:Subscription):void{if(busy.value)return;if(selected.value?.id!==row.id)reason.value="";selected.value=row;}
const labels: Record<string, string> = { revoking: "Revoking", exhausted: "Quota exhausted", suspended: "Suspended", active: "Active", pending_provision: "Pending provisioning", expired: "Expired", failed: "Provisioning failed", cancelled: "Cancelled" };
async function load(): Promise<void> {
  const version=++listVersion; loading.value = true; error.value = "";
  try { const result = await request<Page<Subscription>>(`/v1/admin/subscriptions?${query({ status: status.value || undefined, customer_id: customerId.value ? Number(customerId.value) : undefined, page: page.value })}`); if(version!==listVersion)return; rows.value = result.data; total.value = result.meta.pager?.total_items ?? 0; pages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if(version===listVersion)error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if(version===listVersion)loading.value = false; }
}
async function refresh(): Promise<void> {
  const id = selected.value?.id; await load();
  if (!id) return;
  try { const row = await item<Subscription>(`/v1/admin/subscriptions/${id}`); if (selected.value?.id === id) selected.value = row; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
async function checkLifecycle(): Promise<void> {
  const row = selected.value; if (!row) return; busy.value = true; error.value = ""; notice.value = "";
  try { const result = await item<Subscription>(`/v1/admin/subscriptions/${row.id}/check-lifecycle`, "POST"); if (selected.value?.id === row.id) selected.value = result; notice.value = result.status === "revoking" ? "Revocation requested. Renewal follows final usage reporting and node confirmation." : "Expiry and quota checked."; await load(); }
  catch(cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function toggle(): Promise<void> {
  if (!selected.value) return; busy.value = true; error.value = ""; notice.value = "";
  try { selected.value = await item<Subscription>(`/v1/admin/subscriptions/${selected.value.id}/auto-renew`, "PATCH", { enabled: !selected.value.auto_renew }); notice.value = selected.value.auto_renew ? "Automatic renewal enabled." : "Automatic renewal disabled."; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function refund(): Promise<void> {
  if (!selected.value) return; busy.value = true; error.value = ""; notice.value = "";
  try { selected.value = await item<Subscription>(`/v1/admin/subscriptions/${selected.value.id}/provision-failed`, "POST", { reason: reason.value.trim() }); notice.value = selected.value.entitlement_kind === "trial" ? "Trial cancellation recorded. No payment is charged or refunded." : selected.value.status === "failed" ? "The purchase amount was refunded to the wallet once." : "Revocation requested. The refund follows node confirmation."; reason.value = ""; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
watch([status, customerId], () => { page.value = 1; void load() }); async function selectRoute(): Promise<void> {
  const id = Number(route.query.subscription_id);
  if (!Number.isSafeInteger(id) || id <= 0) return;
  const parent=String(route.query.customer_id??"");const expectedCustomer=Number(parent);
  if (selected.value && (selected.value.id !== id || (parent && selected.value.customer_id !== expectedCustomer))) { selected.value=null; reason.value=""; }
  try { const row = await item<Subscription>(`/v1/admin/subscriptions/${id}`); if(Number(route.query.subscription_id)!==id||String(route.query.customer_id??"")!==parent)return; if(parent&&(!Number.isSafeInteger(expectedCustomer)||expectedCustomer<=0||row.customer_id!==expectedCustomer))throw new Error("This subscription does not belong to the selected customer.");choose(row); }
  catch (cause) { if(Number(route.query.subscription_id)===id&&String(route.query.customer_id??"")===parent)error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
watch(() => [route.query.subscription_id,route.query.customer_id], selectRoute);
watch(() => route.query.customer_id, value => { customerId.value=String(value ?? ""); });
onMounted(() => { void load(); void selectRoute(); });
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">SUBSCRIPTION LIFECYCLE</p><h1>Subscriptions</h1><p class="subtitle">Manage service access, automatic renewal and provisioning recovery.</p></div><button class="btn secondary" @click="load">Refresh</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div class="split"><div class="card"><div class="card-pad"><div class="toolbar"><label class="field"><span>Status</span><select v-model="status"><option value="">All</option><option value="pending_provision">Pending provisioning</option><option value="active">Active</option><option value="expired">Expired</option><option value="failed">Provisioning failed</option><option value="exhausted">Quota exhausted</option><option value="revoking">Revoking</option><option value="suspended">Suspended</option><option value="cancelled">Cancelled</option></select></label><CustomerPicker v-model="customerChoice" :locked="parentLocked" /></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Subscription</th><th>Customer</th><th>Expiry</th><th>Renewal</th><th>Status</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="choose(row)" @keydown.enter="choose(row)"><td class="tabular">{{ faNumber(row.id) }}</td><td class="tabular">{{ faNumber(row.customer_id) }}</td><td>{{ faDate(row.expires_at) }}</td><td><span class="badge" :class="row.auto_renew ? 'success' : ''">{{ row.auto_renew ? 'Automatic' : 'Off' }}</span></td><td><span class="badge" :class="row.status === 'active' ? 'success' : row.status === 'pending_provision' ? 'warning' : 'danger'">{{ labels[row.status] ?? row.status }}</span></td></tr></tbody></table><div v-if="!loading && !rows.length && !error" class="empty">No subscriptions match this status.</div><div v-if="loading" class="empty">Loading subscriptions…</div></div><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} Subscription</span><button :disabled="page >= pages" @click="page++; load()">›</button></div></div>
  <div class="card card-pad"><h2>Subscription details</h2><div v-if="selected" class="form-grid"><p v-if="selected.entitlement_kind==='trial'" class="badge">Trial · No automatic renewal</p><RouterLink v-if="auth.can('support')" class="btn secondary" :to="{path:'/support',query:{customer_id:selected.customer_id,subscription_id:selected.id}}">Service support</RouterLink><div class="detail-line"><span>ID</span><strong>{{ faNumber(selected.id) }}</strong></div><div class="detail-line"><span>Customer</span><strong>{{ faNumber(selected.customer_id) }}</strong></div><IpPolicySummary :purchased="selected.purchased_ip_policy" :effective="selected.effective_ip_policy"/><div class="detail-line"><span>Purchased delivery group</span><strong>{{ selected.group_id === null ? 'No group (direct configuration)' : faNumber(selected.group_id) }}</strong></div><div class="detail-line"><span>Usage Period (bytes)</span><strong>{{ faNumber(selected.used_bytes) }} of {{ (selected.quota_bytes === null ? "Unlimited" : faNumber(selected.quota_bytes)) }}</strong></div><button v-if="auth.can('subscriptions', 'create') && selected.status === 'active'" class="btn secondary" :disabled="busy" @click="checkLifecycle">Check expiry and quota</button><div class="detail-line"><span>Price per period</span><strong>{{ toman(selected.price_rial) }}</strong></div><div class="detail-line"><span>Duration per period</span><strong>{{ selected.duration_days === null ? "No expiry" : faNumber(selected.duration_days) + " days" }}</strong></div><div class="detail-line"><span>Renewal count</span><strong>{{ faNumber(selected.renewal_count) }}</strong></div><div class="detail-line"><span>Status</span><strong>{{ labels[selected.status] ?? selected.status }}</strong></div><button v-if="auth.can('subscriptions', 'update') && selected.entitlement_kind !== 'trial' && selected.status !== 'failed' && selected.status !== 'cancelled'" class="btn secondary" :disabled="busy" @click="toggle">{{ selected.auto_renew ? 'Disable automatic renewal' : 'Enable automatic renewal' }}</button><template v-if="selected.status === 'pending_provision' && selected.activated_at === null && auth.can('subscriptions', 'create')"><div class="hint-box">Request revocation after confirming the provisioning failure. Refunds wait for revocation confirmation if a node may have applied access.</div><label class="field"><span>Provisioning failure reason</span><textarea v-model="reason" minlength="3" maxlength="250" /></label><button class="btn danger" :disabled="busy || reason.trim().length < 3" @click="refund">{{ selected.entitlement_kind==='trial'?'Request trial cancellation':'Request revocation and refund' }}</button></template><SubscriptionControl :subscription="selected" @changed="selected = $event; refresh()" /><p v-if="selected.failure_reason" class="message error">{{ selected.failure_reason }}</p></div><div v-else class="empty">Select a subscription to view details and manage its service.</div></div></div>
  <div v-if="selected" class="card card-pad"><SubscriptionProvisioning :subscription-id="selected.id" @changed="refresh" /></div>
  <div v-if="selected" class="card card-pad"><UsageRecords :subscription-id="selected.id" /></div>
  <div v-if="selected" class="card card-pad"><SubscriptionIpLimit :subscription-id="selected.id" @changed="refresh" /></div>
</template>
