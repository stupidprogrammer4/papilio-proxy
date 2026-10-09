<script setup lang="ts">
import Modal from "@papilio/ui/Modal.vue";
import CustomerConfigurations from "../components/CustomerConfigurations.vue";
import PlanConfigurations from "../components/PlanConfigurations.vue";
import TrialOffer from "../components/trials/TrialOffer.vue";
import { useAuth } from "@papilio/auth";
import { onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, item, query, request, type Customer, type Page, type Plan, type Subscription, type Topup, type WalletBalance } from "@papilio/api";
import { faNumber, toman } from "@papilio/ui";
import CustomerAccess from "../components/CustomerAccess.vue";
import NumField from "@papilio/ui/NumField.vue";

const auth = useAuth();
const rows = ref<Customer[]>([]); const total = ref(0); const page = ref(1); const pages = ref(1); const q = ref(""); const selected = ref<Customer | null>(null);
const wallet = ref<number | null>(null); const plans = ref<Plan[]>([]); const planTotal = ref(0); const planPage = ref(1); const planPages = ref(1); const planQ = ref(""); const chosenPlan = ref<Plan | null>(null);
const name = ref(""); const telegram = ref(""); const topupAmount = ref(""); const autoRenew = ref(false); const busy = ref(false); const loading = ref(false); const error = ref(""); const notice = ref("");
const creationAccess = ref<import("@papilio/api").CustomerAccessState|null>(null);
async function loadCreationPolicy(): Promise<void> { try { creationAccess.value = await item<import("@papilio/api").CustomerAccessState>("/v1/admin/customers/creation-policy"); } catch(cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; } }
function accessChanged(row: Customer): void { if(selected.value?.id === row.id) selected.value = row; rows.value = rows.value.map(current => current.id === row.id ? row : current); }
const purchaseKey = ref(""); const profileName = ref("");
let selectionVersion = 0;
let alive = true, customerListVersion = 0, planListVersion = 0;
let customerRead: AbortController | null = null, planRead: AbortController | null = null;

async function load(): Promise<void> {
  const version = ++customerListVersion;
  customerRead?.abort();
  const read = new AbortController(); customerRead = read;
  loading.value = true; error.value = "";
  try {
    const result = await request<Page<Customer>>(`/v1/admin/customers?${query({ q: q.value, page: page.value })}`, "GET", undefined, { signal: read.signal });
    if (!alive || version !== customerListVersion) return;
    rows.value = result.data; total.value = result.meta.pager?.total_items ?? 0; pages.value = result.meta.pager?.total_pages ?? 1;
  } catch (cause) { if (alive && version === customerListVersion && !read.signal.aborted) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (alive && version === customerListVersion) { loading.value = false; customerRead = null; } }
}
async function loadPlans(): Promise<void> {
  const version = ++planListVersion;
  planRead?.abort();
  const read = new AbortController(); planRead = read;
  try {
    const result = await request<Page<Plan>>(`/v1/plans?${query({ q: planQ.value, page: planPage.value })}`, "GET", undefined, { signal: read.signal });
    if (!alive || version !== planListVersion) return;
    plans.value = result.data; planTotal.value = result.meta.pager?.total_items ?? 0; planPages.value = result.meta.pager?.total_pages ?? 1;
  } catch (cause) { if (alive && version === planListVersion && !read.signal.aborted) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (alive && version === planListVersion) planRead = null; }
}
async function select(row: Customer, force = false): Promise<void> {
  if (busy.value && !force) return; const version = ++selectionVersion; profileName.value = row.display_name;
  selected.value = row; chosenPlan.value = null; purchaseKey.value = ""; wallet.value = null; error.value = "";
  try { if (!auth.can("payments")) return; const balance = await item<WalletBalance>(`/v1/admin/payments/wallets/${row.id}`); if (version === selectionVersion) wallet.value = balance.balance_rial; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
async function saveProfile(): Promise<void> {
  const row = selected.value; if (!row || busy.value || !auth.can("customers", "update")) return;
  busy.value = true; error.value = ""; notice.value = "";
  try { const result = await item<Customer>(`/v1/admin/customers/${row.id}/profile`, "PUT", { display_name: profileName.value.trim() }); if (selected.value?.id === row.id) selected.value = result; notice.value = "Customer name saved."; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function create(): Promise<void> {
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const row = await item<Customer>("/v1/admin/customers", "POST", { display_name: name.value.trim(), access: creationAccess.value, telegram_id: telegram.value ? Number(telegram.value) : null });
    createOpen.value=false; name.value = ""; telegram.value = ""; notice.value = "Customer created."; page.value = 1; await load(); await select(row, true);
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function topup(): Promise<void> {
  if (!selected.value) return;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const result = await item<Topup>("/v1/admin/payments/topups", "POST", { customer_id: selected.value.id, amount_rial: Number(topupAmount.value) * 10 });
    topupAmount.value = ""; notice.value = `Top-up request #${faNumber(result.id)} created. Review it in Payments.`;
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function purchase(): Promise<void> {
  if (!selected.value || !chosenPlan.value) return;
  busy.value = true; error.value = ""; notice.value = "";
  if (!purchaseKey.value) purchaseKey.value = crypto.randomUUID();
  try {
    const result = await item<Subscription>("/v1/admin/subscriptions", "POST", { purchase_key: purchaseKey.value, customer_id: selected.value.id, plan_id: chosenPlan.value.id, expected_price_rial: chosenPlan.value.price_rial, auto_renew: autoRenew.value });
    wallet.value = (await item<WalletBalance>(`/v1/admin/payments/wallets/${selected.value.id}`)).balance_rial;
    notice.value = `Subscription #${faNumber(result.id)} purchased and queued for provisioning.`; chosenPlan.value = null; purchaseKey.value = "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again.";
    if(cause instanceof ApiError && cause.code === "purchase_price_changed" && chosenPlan.value) {
      const id=chosenPlan.value.id;
      try { const updated=await item<Plan>(`/v1/admin/plans/${id}`); if(chosenPlan.value?.id===id) chosenPlan.value=updated; }
      catch(refreshError) { error.value=refreshError instanceof Error ? refreshError.message : "Could not refresh the price."; }
    }
  }
  finally { busy.value = false; }
}
watch(q, () => { page.value = 1; void load() }); watch(planQ, () => { planPage.value = 1; void loadPlans() });
watch(() => chosenPlan.value?.id, () => { purchaseKey.value = ""; });
onMounted(() => { void load(); void loadPlans(); void loadCreationPolicy() });
onUnmounted(() => { alive = false; ++customerListVersion; ++planListVersion; customerRead?.abort(); planRead?.abort(); });
const createOpen=ref(false);
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">CUSTOMER WORKSPACE</p><h1>Customers</h1><p class="subtitle">Manage accounts, assigned configurations and wallet purchases.</p></div><button v-if="auth.can('customers','create')" class="btn" :disabled="busy" @click="createOpen=true">+ Create customer</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div :class="{ split: Boolean(selected) }">
    <div class="card"><div class="card-pad"><div class="toolbar"><label class="field"><span>Search customers</span><input v-model="q" placeholder="Customer name" /></label></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>ID</th><th>Name</th><th>Telegram</th><th>Status</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="select(row)" @keydown.enter="select(row)"><td class="tabular">{{ faNumber(row.id) }}</td><td><strong>{{ row.display_name }}</strong></td><td class="tabular">{{ row.telegram_id ? faNumber(row.telegram_id) : '—' }}</td><td><span class="badge" :class="row.is_active ? 'success' : 'danger'">{{ row.is_active ? 'Active' : 'Inactive' }}</span></td></tr></tbody></table><div v-if="!loading && !rows.length" class="empty">No customers found.</div><div v-if="loading" class="empty">Loading customers…</div></div><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} Customer</span><button :disabled="page >= pages" @click="page++; load()">›</button></div></div>
    <div class="stack"><Modal v-if="auth.can('customers', 'create')" v-model="createOpen" title="Create customer" :busy="busy" wide><p v-if="error" class="message error" role="alert">{{error}}</p><form class="form-grid" @submit.prevent="create"><label class="field"><span>Display name</span><input v-model="name" required maxlength="120" /></label><NumField v-model="telegram" label="Telegram ID (optional)" /><template v-if="creationAccess"><label class="check-row"><input v-model="creationAccess.is_active" type="checkbox" />Allow customer sign in</label><label class="check-row"><input v-model="creationAccess.services_enabled" type="checkbox" />Enable service access</label><label class="check-row"><input v-model="creationAccess.renewals_enabled" type="checkbox" />Allow renewals</label></template><button class="btn" :disabled="busy || !name.trim() || !creationAccess">Create customer</button></form></Modal>
      <div v-if="selected" class="card card-pad"><h2>Account: {{ selected.display_name }}</h2><div class="detail-line"><span>Customer ID</span><strong>{{ faNumber(selected.id) }}</strong></div><form v-if="auth.can('customers','update')" class="form-grid" @submit.prevent="saveProfile"><label class="field"><span>Customer display name</span><input v-model="profileName" maxlength="120" required :disabled="busy" /></label><button class="btn secondary" :disabled="busy || !profileName.trim()">Save name</button></form><RouterLink v-if="auth.can('subscriptions')" class="btn secondary" :to="`/subscriptions?customer_id=${selected.id}`">Customer subscriptions</RouterLink><RouterLink v-if="auth.can('notifications')" class="btn secondary" :to="{path:'/notifications',query:{customer_id:selected.id}}">Customer notifications</RouterLink><RouterLink v-if="auth.can('support')" class="btn secondary" :to="{path:'/support',query:{customer_id:selected.id}}">Customer support</RouterLink><div v-if="auth.can('payments')" class="detail-line"><span>Wallet balance</span><strong>{{ wallet === null ? '…' : toman(wallet) }}</strong></div><RouterLink v-if="auth.can('payments')" class="btn secondary" :to="`/customers/${selected.id}/wallet`">Wallet activity</RouterLink><form v-if="auth.can('payments', 'create')" class="form-grid" style="margin-top:20px" @submit.prevent="topup"><NumField v-model="topupAmount" label="Top-up amount (toman)" /><button class="btn secondary" :disabled="busy || !Number(topupAmount)">Create top-up request</button></form></div>
      <CustomerConfigurations v-if="selected && auth.can('network') && auth.can('subscriptions')" :key="`configs-${selected.id}`" :customer-id="selected.id" /><TrialOffer v-if="selected && auth.can('subscriptions')" :key="selected.id" :customer-id="selected.id" admin :can-claim="auth.can('subscriptions','create')" />
      <CustomerAccess v-if="selected" :customer="selected" @changed="accessChanged" />
      <div v-if="selected && auth.can('subscriptions', 'create') && auth.can('payments')" class="card card-pad"><h2>Purchase with wallet</h2><div class="form-grid"><label class="field"><span>Find a plan</span><input v-model="planQ" placeholder="Plan name" /></label><div class="table-wrap"><table class="data-table"><tbody><tr v-for="plan in plans" :key="plan.id" :class="{ 'selected-row': chosenPlan?.id === plan.id }" tabindex="0" @click="chosenPlan = plan" @keydown.enter="chosenPlan = plan"><td>{{ plan.title }}</td><td class="tabular">{{ toman(plan.price_rial) }}</td></tr></tbody></table><div v-if="!plans.length" class="empty">No active plans found.</div></div><div class="pager"><button :disabled="planPage <= 1" @click="planPage--; loadPlans()">‹</button><span>{{ faNumber(planPage) }} of {{ faNumber(planPages) }}</span><button :disabled="planPage >= planPages" @click="planPage++; loadPlans()">›</button></div><label class="field" style="flex-direction:row; align-items:center"><input v-model="autoRenew" type="checkbox" style="width:auto;min-height:0" /> Automatic wallet renewal</label><div v-if="chosenPlan" class="hint-box">{{ chosenPlan.title }} · {{ toman(chosenPlan.price_rial) }} will be deducted from the wallet. Service activation follows successful node provisioning.</div><PlanConfigurations v-if="chosenPlan" :plan-id="chosenPlan.id" public /><button class="btn" :disabled="busy || !chosenPlan || wallet === null || wallet < chosenPlan.price_rial" @click="purchase">Purchase selected plan</button></div></div>
    </div>
  </div>
</template>
