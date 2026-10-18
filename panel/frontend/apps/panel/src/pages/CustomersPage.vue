<script setup lang="ts">
import Modal from "@papilio/ui/Modal.vue";
import CustomerConfigurations from "../components/CustomerConfigurations.vue";
import PlanConfigurations from "../components/PlanConfigurations.vue";
import TrialOffer from "../components/trials/TrialOffer.vue";
import { useAuth } from "@papilio/auth";
import { onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, item, query, request, type Customer, type Page, type Plan, type Subscription, type Topup, type WalletBalance } from "@papilio/api";
import { useLocalizedFormats } from "../composables/useLocalizedFormats";
import CustomerAccess from "../components/CustomerAccess.vue";
import NumField from "@papilio/ui/NumField.vue";

const auth = useAuth();
const { t } = useI18n();
const { toman, number: faNumber } = useLocalizedFormats();
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
  try { const result = await item<Customer>(`/v1/admin/customers/${row.id}/profile`, "PUT", { display_name: profileName.value.trim() }); if (selected.value?.id === row.id) selected.value = result; notice.value = t("customers.profileSaved"); await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function create(): Promise<void> {
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const row = await item<Customer>("/v1/admin/customers", "POST", { display_name: name.value.trim(), access: creationAccess.value, telegram_id: telegram.value ? Number(telegram.value) : null });
    createOpen.value=false; name.value = ""; telegram.value = ""; notice.value = t("customers.created"); page.value = 1; await load(); await select(row, true);
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { busy.value = false; }
}
async function topup(): Promise<void> {
  if (!selected.value) return;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const result = await item<Topup>("/v1/admin/payments/topups", "POST", { customer_id: selected.value.id, amount_rial: Number(topupAmount.value) * 10 });
    topupAmount.value = ""; notice.value = t("customers.topupCreated", { id: faNumber(result.id) });
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
    notice.value = t("customers.purchaseQueued", { id: faNumber(result.id) }); chosenPlan.value = null; purchaseKey.value = "";
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
    <div class="page-head"><div><p class="eyebrow">{{ t('customers.eyebrow') }}</p><h1>{{ t('customers.title') }}</h1><p class="subtitle">{{ t('customers.description') }}</p></div><button v-if="auth.can('customers','create')" class="btn" :disabled="busy" @click="createOpen=true">{{ t('customers.create') }}</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div :class="{ split: Boolean(selected) }">
    <div class="card"><div class="card-pad"><div class="toolbar"><label class="field"><span>{{ t('customers.search') }}</span><input v-model="q" :placeholder="t('customers.name')" /></label></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t('customers.id') }}</th><th>{{ t('customers.name') }}</th><th>{{ t('customers.telegram') }}</th><th>{{ t('customers.status') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="select(row)" @keydown.enter="select(row)"><td class="tabular">{{ faNumber(row.id) }}</td><td><strong>{{ row.display_name }}</strong></td><td class="tabular">{{ row.telegram_id ? faNumber(row.telegram_id) : '—' }}</td><td><span class="badge" :class="row.is_active ? 'success' : 'danger'">{{ row.is_active ? t('customers.active') : t('customers.inactive') }}</span></td></tr></tbody></table><div v-if="!loading && !rows.length" class="empty">{{ t('customers.empty') }}</div><div v-if="loading" class="empty">{{ t('customers.loading') }}</div></div><div class="pager"><button :disabled="page <= 1" :aria-label="t('customers.previousPage')" @click="page--; load()">‹</button><span>{{ t('customers.pageCount', { page: faNumber(page), total: faNumber(total) }) }}</span><button :disabled="page >= pages" :aria-label="t('customers.nextPage')" @click="page++; load()">›</button></div></div>
    <div class="stack"><Modal v-if="auth.can('customers', 'create')" v-model="createOpen" :title="t('customers.createTitle')" :busy="busy" wide><p v-if="error" class="message error" role="alert">{{error}}</p><form class="form-grid" @submit.prevent="create"><label class="field"><span>{{ t('customers.displayName') }}</span><input v-model="name" required maxlength="120" /></label><NumField v-model="telegram" :label="t('customers.telegramOptional')" /><template v-if="creationAccess"><label class="check-row"><input v-model="creationAccess.is_active" type="checkbox" />{{ t('customers.allowSignIn') }}</label><label class="check-row"><input v-model="creationAccess.services_enabled" type="checkbox" />{{ t('customers.enableService') }}</label><label class="check-row"><input v-model="creationAccess.renewals_enabled" type="checkbox" />{{ t('customers.allowRenewals') }}</label></template><button class="btn" :disabled="busy || !name.trim() || !creationAccess">{{ t('customers.create') }}</button></form></Modal>
      <div v-if="selected" class="card card-pad">
        <h2>{{ t("customers.accountTitle", { name: selected.display_name }) }}</h2>
        <div class="detail-line"><span>{{ t("customers.customerId") }}</span><strong>{{ faNumber(selected.id) }}</strong></div>
        <form v-if="auth.can('customers','update')" class="form-grid" @submit.prevent="saveProfile">
          <label class="field"><span>{{ t("customers.profileName") }}</span><input v-model="profileName" maxlength="120" required :disabled="busy" /></label>
          <button class="btn secondary" :disabled="busy || !profileName.trim()">{{ t("customers.saveName") }}</button>
        </form>
        <RouterLink v-if="auth.can('subscriptions')" class="btn secondary" :to="`/subscriptions?customer_id=${selected.id}`">{{ t("customers.subscriptionsLink") }}</RouterLink>
        <RouterLink v-if="auth.can('notifications')" class="btn secondary" :to="{path:'/notifications',query:{customer_id:selected.id}}">{{ t("customers.notificationsLink") }}</RouterLink>
        <RouterLink v-if="auth.can('support')" class="btn secondary" :to="{path:'/support',query:{customer_id:selected.id}}">{{ t("customers.supportLink") }}</RouterLink>
        <div v-if="auth.can('payments')" class="detail-line"><span>{{ t("customers.walletBalance") }}</span><strong>{{ wallet === null ? '…' : toman(wallet) }}</strong></div>
        <RouterLink v-if="auth.can('payments')" class="btn secondary" :to="`/customers/${selected.id}/wallet`">{{ t("customers.walletActivity") }}</RouterLink>
        <form v-if="auth.can('payments', 'create')" class="form-grid" style="margin-top:20px" @submit.prevent="topup">
          <NumField v-model="topupAmount" :label="t('customers.topupAmountToman')" />
          <button class="btn secondary" :disabled="busy || !Number(topupAmount)">{{ t("customers.createTopup") }}</button>
        </form>
      </div>
      <CustomerConfigurations v-if="selected && auth.can('network') && auth.can('subscriptions')" :key="`configs-${selected.id}`" :customer-id="selected.id" /><TrialOffer v-if="selected && auth.can('subscriptions')" :key="selected.id" :customer-id="selected.id" admin :can-claim="auth.can('subscriptions','create')" />
      <CustomerAccess v-if="selected" :customer="selected" @changed="accessChanged" />
      <div v-if="selected && auth.can('subscriptions', 'create') && auth.can('payments')" class="card card-pad">
        <h2>{{ t("customers.purchaseTitle") }}</h2>
        <div class="form-grid">
          <label class="field"><span>{{ t("customers.findPlan") }}</span><input v-model="planQ" :placeholder="t('customers.planNamePlaceholder')" /></label>
          <div class="table-wrap">
            <table class="data-table"><tbody><tr v-for="plan in plans" :key="plan.id" :class="{ 'selected-row': chosenPlan?.id === plan.id }" tabindex="0" @click="chosenPlan = plan" @keydown.enter="chosenPlan = plan"><td>{{ plan.title }}</td><td class="tabular">{{ toman(plan.price_rial) }}</td></tr></tbody></table>
            <div v-if="!plans.length" class="empty">{{ t("customers.noActivePlans") }}</div>
          </div>
          <div class="pager"><button :disabled="planPage <= 1" :aria-label="t('customers.previousPlanPage')" @click="planPage--; loadPlans()">‹</button><span>{{ t("customers.planPageCount", { page: faNumber(planPage), total: faNumber(planPages) }) }}</span><button :disabled="planPage >= planPages" :aria-label="t('customers.nextPlanPage')" @click="planPage++; loadPlans()">›</button></div>
          <label class="field" style="flex-direction:row; align-items:center"><input v-model="autoRenew" type="checkbox" style="width:auto;min-height:0" /> {{ t("customers.automaticRenewal") }}</label>
          <div v-if="chosenPlan" class="hint-box">{{ t("customers.planPriceHint", { title: chosenPlan.title, price: toman(chosenPlan.price_rial) }) }}</div>
          <PlanConfigurations v-if="chosenPlan" :plan-id="chosenPlan.id" public />
          <button class="btn" :disabled="busy || !chosenPlan || wallet === null || wallet < chosenPlan.price_rial" @click="purchase">{{ t("customers.purchaseSelectedPlan") }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
