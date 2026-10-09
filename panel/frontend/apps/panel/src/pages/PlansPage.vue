<script setup lang="ts">
import Modal from "@papilio/ui/Modal.vue";
import { useAuth } from "@papilio/auth";
import { onMounted, ref, watch } from "vue";
import { item, query, request, type Page, type Plan, type FulfillmentPolicy, type IpLimitChoice, type PlanPolicyDefaults, type QuotaPolicy } from "@papilio/api";
import { faNumber, toman } from "@papilio/ui";
import PlanConfigurations from "../components/PlanConfigurations.vue";
import QuotaPolicyEditor from "../components/QuotaPolicyEditor.vue";
import FulfillmentPolicyEditor from "../components/FulfillmentPolicyEditor.vue";
import SourceIpAllowanceEditor from "../components/SourceIpAllowanceEditor.vue";
import PlanIpAllowance from "../components/PlanIpAllowance.vue";
import { ipAllowanceText } from "../components/ipLimits/policy";
import PlanGroupPicker from "../components/PlanGroupPicker.vue";
import NumField from "@papilio/ui/NumField.vue";
const auth = useAuth();
const rows = ref<Plan[]>([]); const total = ref(0); const page = ref(1); const pages = ref(1); const q = ref(""); const active = ref(""); const selected = ref<Plan | null>(null); const loading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref("");
const groupId = ref<number | null>(null);
const quotaPolicy = ref<QuotaPolicy | null>(null); const overrideQuota = ref(false); const defaults = ref<PlanPolicyDefaults | null>(null); const fulfillment = ref<FulfillmentPolicy | null>(null); const ipLimit = ref<IpLimitChoice | null>(null); const overrideFulfillment = ref(false); const ipValid = ref(false); const defaultsError = ref("");
const detailOpen = ref(false); const detail = ref<Plan | null>(null);
function inspect(row: Plan): void { detail.value = row; detailOpen.value = true; }
const editing = ref(false); const sortOrder = ref("");
const planType = ref<"quota_timed" | "quota_only" | "time_only">("quota_timed");
const code = ref(""); const title = ref(""); const quota = ref(""); const duration = ref(""); const price = ref("");
async function load(): Promise<void> {
  loading.value = true; error.value = "";
  try { const result = await request<Page<Plan>>(`/v1/admin/plans?${query({ q: q.value, active: active.value || undefined, page: page.value })}`); rows.value = result.data; total.value = result.meta.pager?.total_items ?? 0; pages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { loading.value = false; }
}
async function create(): Promise<void> {
  if (!ipValid.value) return;
  busy.value = true; error.value = ""; notice.value = "";
  try { await item<Plan>("/v1/admin/plans", "POST", { quota_policy: overrideQuota.value ? quotaPolicy.value : null, fulfillment: overrideFulfillment.value ? fulfillment.value : null, ip_limit: ipLimit.value, group_id: groupId.value, code: code.value.trim(), title: title.value.trim(), quota_bytes: planType.value === "time_only" ? null : Number(quota.value) * 1_073_741_824, duration_days: planType.value === "quota_only" ? null : Number(duration.value), price_rial: Math.round(Number(price.value) * 10), sort_order: Number(sortOrder.value) }); code.value = ""; title.value = ""; quota.value = ""; price.value = ""; createOpen.value=false; notice.value = "Plan created as inactive. Review it before publishing."; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
function edit(row: Plan): void { createOpen.value=true;
  overrideQuota.value = row.quota_policy !== null; quotaPolicy.value = row.quota_policy ? { ...row.quota_policy } : defaults.value ? { ...defaults.value.quota_policy } : null; overrideFulfillment.value = row.fulfillment !== null; fulfillment.value = row.fulfillment ? { ...row.fulfillment } : defaults.value ? { ...defaults.value.fulfillment } : null; ipLimit.value = row.ip_limit ? { ...row.ip_limit } : null; groupId.value = row.group_id; selected.value = row; editing.value = true; code.value = row.code; title.value = row.title;
  planType.value = row.quota_bytes === null ? "time_only" : row.duration_days === null ? "quota_only" : "quota_timed"; quota.value = row.quota_bytes === null ? "" : String(row.quota_bytes); duration.value = row.duration_days === null ? "" : String(row.duration_days); price.value = String(row.price_rial / 10); sortOrder.value = String(row.sort_order);
}
function clear(): void { planType.value = "quota_timed"; overrideQuota.value = false; quotaPolicy.value = defaults.value ? { ...defaults.value.quota_policy } : null; overrideFulfillment.value = false; fulfillment.value = defaults.value ? { ...defaults.value.fulfillment } : null; ipLimit.value = null; ipValid.value = false; groupId.value = null; selected.value = null; editing.value = false; code.value = ""; title.value = ""; quota.value = ""; duration.value = ""; price.value = ""; sortOrder.value = ""; }
async function save(): Promise<void> {
  if (!selected.value || !ipValid.value) return; busy.value = true; error.value = "";
  try { await item<Plan>(`/v1/admin/plans/${selected.value.id}`, "PATCH", { quota_policy: overrideQuota.value ? quotaPolicy.value : null, fulfillment: overrideFulfillment.value ? fulfillment.value : null, ip_limit: ipLimit.value, group_id: groupId.value, title: title.value.trim(), quota_bytes: planType.value === "time_only" ? null : Number(quota.value), duration_days: planType.value === "quota_only" ? null : Number(duration.value), price_rial: Math.round(Number(price.value) * 10), sort_order: Number(sortOrder.value) }); createOpen.value=false; notice.value = "Plan changes saved."; clear(); await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function toggle(row: Plan): Promise<void> {
  busy.value = true; error.value = ""; notice.value = "";
  try { const updated = await item<Plan>(`/v1/admin/plans/${row.id}/active`, "PATCH", { is_active: !row.is_active }); notice.value = updated.is_active ? "Plan published." : "Plan unpublished."; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function loadDefaults(): Promise<void> {
  defaultsError.value = "";
  try { const result = await item<PlanPolicyDefaults>("/v1/admin/plans/policy-defaults"); defaults.value = result; if (!overrideQuota.value) quotaPolicy.value = { ...result.quota_policy }; if (!overrideFulfillment.value) fulfillment.value = { ...result.fulfillment }; }
  catch (cause) { defaultsError.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
watch([q, active], () => { page.value = 1; void load() }); onMounted(() => { void load(); void loadDefaults(); });
const createOpen=ref(false);
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">PRODUCT CATALOG</p><h1>Plans</h1><p class="subtitle">Build flexible plans with clear pricing, limits and configuration bundles.</p></div><button v-if="auth.can('catalog','create')" class="btn" :disabled="busy" @click="clear();createOpen=true">+ Create plan</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div><div class="card"><div class="card-pad"><div class="toolbar"><label class="field"><span>Search</span><input v-model="q" placeholder="Plan name" /></label><label class="field"><span>Status</span><select v-model="active"><option value="">All</option><option value="true">Active</option><option value="false">Inactive</option></select></label></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Plan</th><th>Data</th><th>Duration</th><th>Price</th><th>Source IPs</th><th>Status</th><th>Actions</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td><strong>{{ row.title }}</strong><br /><small class="mono">{{ row.code }}</small></td><td class="tabular">{{ row.quota_bytes === null ? "Unlimited" : faNumber(row.quota_bytes / 1_073_741_824) + " GiB" }}</td><td class="tabular">{{ row.duration_days === null ? "No expiry" : faNumber(row.duration_days) + " days" }}</td><td class="tabular">{{ toman(row.price_rial) }}</td><td>{{row.effective_ip_policy ? ipAllowanceText(row.effective_ip_policy.policy) : row.ip_limit ? ipAllowanceText(row.ip_limit) : "Allowance unavailable"}}<br/><small>{{row.effective_ip_policy?.source==='current_defaults'?'Purchase-time defaults':row.ip_limit?'Explicit plan terms':'Effective policy unavailable'}}</small></td><td><span class="badge" :class="row.is_active ? 'success' : 'warning'">{{ row.is_active ? 'Active' : 'Inactive' }}</span></td><td><div class="inline-actions"><button class="btn small secondary" @click="inspect(row)">Details</button><button v-if="auth.can('catalog', 'update')" class="btn small secondary" @click="edit(row)">Edit</button> <button v-if="auth.can('catalog', 'update')" class="btn small secondary" :disabled="busy" @click="toggle(row)">{{ row.is_active ? 'Unpublish' : 'Publish' }}</button></div></td></tr></tbody></table><div v-if="!loading && !rows.length" class="empty">No plans found.</div><div v-if="loading" class="empty">Loading plans…</div></div><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} Plan</span><button :disabled="page >= pages" @click="page++; load()">›</button></div></div>
  <Modal v-model="detailOpen" :title="detail?.title ?? 'Plan details'" wide><section v-if="detail" class="form-grid"><p class="mono">{{detail.code}}</p><div class="detail-line"><span>Price</span><strong>{{toman(detail.price_rial)}}</strong></div><div class="detail-line"><span>Data allowance</span><strong>{{detail.quota_bytes===null?'Unlimited':faNumber(detail.quota_bytes/1_073_741_824)+' GiB'}}</strong></div><div class="detail-line"><span>Duration</span><strong>{{detail.duration_days===null?'No expiry':faNumber(detail.duration_days)+' days'}}</strong></div><div class="detail-line"><span>Catalog status</span><span class="badge" :class="detail.is_active?'success':'warning'">{{detail.is_active?'Published':'Unpublished'}}</span></div><PlanIpAllowance :policy="detail.effective_ip_policy" :configured="detail.ip_limit"/><PlanConfigurations :plan-id="detail.id"/><button v-if="auth.can('catalog','update')" class="btn secondary" @click="detailOpen=false;edit(detail)">Edit this plan</button></section></Modal>
  <Modal v-if="auth.can('catalog', editing ? 'update' : 'create')" v-model="createOpen" :title="editing ? 'Edit plan' : 'Create plan'" :busy="busy" wide><p v-if="error" class="message error" role="alert">{{error}}</p><form class="form-grid" @submit.prevent="editing ? save() : create()"><label class="field"><span>Unique code</span><input v-model="code" :readonly="editing" required maxlength="64" pattern="[A-Za-z0-9_-]+" dir="ltr" /></label><label class="field"><span>Display name</span><input v-model="title" required maxlength="100" /></label><label class="field"><span>Plan type</span><select aria-label="Plan type" v-model="planType"><option value="quota_timed">Data quota + duration</option><option value="quota_only">Data quota, no expiry</option><option value="time_only">Duration, unlimited data</option></select></label><NumField v-if="planType !== 'time_only'" v-model="quota" :label="editing ? 'Exact quota (bytes)' : 'Data quota (GiB)'" /><NumField v-if="planType !== 'quota_only'" v-model="duration" label="Duration (days)" /><NumField v-model="price" decimal label="Price (toman)" /><NumField v-model="sortOrder" signed label="Display order" /><PlanGroupPicker v-if="auth.can('network')" v-model="groupId" /><p v-else>Network read access is required to select a configuration bundle.</p><PlanConfigurations v-if="selected" :plan-id="selected.id" /><h3>Plan policies</h3><p v-if="planType === 'quota_only'">For quota-only auto-renewal, choose the quota or either renewal trigger.</p><p>Default policies are saved with each purchase. Later plan changes do not alter existing subscriptions.</p><p v-if="defaultsError" class="message error">{{ defaultsError }} <button type="button" class="btn secondary" @click="loadDefaults">Reload defaults</button></p><label class="check-row"><input v-model="overrideFulfillment" type="checkbox" :disabled="!fulfillment" />Override delivery and renewal policy</label><FulfillmentPolicyEditor v-if="overrideFulfillment && fulfillment" v-model="fulfillment" /><label class="check-row"><input v-model="overrideQuota" type="checkbox" :disabled="!quotaPolicy" />Override shared quota policy</label><QuotaPolicyEditor v-if="overrideQuota && quotaPolicy" v-model="quotaPolicy" /><SourceIpAllowanceEditor :key="selected?.id ?? 'new-plan'" v-model="ipLimit" :defaults="defaults?.ip_limit ?? null" :capacity="defaults?.ip_limit_capacity ?? null" :allow-legacy="editing && selected?.ip_limit === null" @validity="ipValid=$event" /><button class="btn" :disabled="busy || !ipValid || !code || !title || (planType !== 'time_only' && !Number(quota)) || (planType !== 'quota_only' && !Number(duration))">{{ editing ? 'Save plan' : 'Create plan' }}</button><button v-if="editing" type="button" class="btn secondary" @click="createOpen=false;clear()">Cancel editing</button></form></Modal></div>
</template>
