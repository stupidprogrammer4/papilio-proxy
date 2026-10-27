<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { query, request, type CustomerAccount, type CustomerAccountPage, type ManagedNode, type ManagedNodePage } from "@papilio/api";
import { faNumber } from "@papilio/ui";
import Icon from "@papilio/ui/Icon.vue";
import { useAuth } from "@papilio/auth";
const auth = useAuth();
const { t } = useI18n();
const loading = ref(false);
const customers = ref<CustomerAccount[]>([]);
const customerPage = ref(1);
const customerPages = ref(1);
const customerTotal = ref(0);
const customerQuery = ref("");
const customerLoading = ref(false);
const customerError = ref("");
const nodes = ref<ManagedNode[]>([]);
const nodePage = ref(1);
const nodePages = ref(1);
const nodeTotal = ref(0);
const nodeQuery = ref("");
const nodeLoading = ref(false);
const nodeError = ref("");
let alive = true;
let customerVersion = 0;
let nodeVersion = 0;
let customerTimer: ReturnType<typeof setTimeout> | null = null;
let nodeTimer: ReturnType<typeof setTimeout> | null = null;
let customerRead: AbortController | null = null;
let nodeRead: AbortController | null = null;
async function loadCustomers(): Promise<void> {
  if (!auth.can("customers")) return;
  const version = ++customerVersion;
  customerRead?.abort();
  const read = new AbortController();
  customerRead = read;
  customerLoading.value = true;
  customerError.value = "";
  try {
    const result = await request<CustomerAccountPage>(
      `/v1/customer-accounts?${query({q: customerQuery.value, page: customerPage.value, page_size: 20})}`,
      "GET",
      undefined,
      {signal: read.signal},
    );
    if (!alive || version !== customerVersion) return;
    customers.value = result.items;
    customerTotal.value = result.count;
    customerPages.value = Math.max(1, Math.ceil(result.count / result.page_size));
  } catch (cause) {
    if (alive && version === customerVersion && !read.signal.aborted) {
      customerError.value = cause instanceof Error ? cause.message : t("dashboard.listError");
    }
  } finally {
    if (alive && version === customerVersion) {
      customerLoading.value = false;
      customerRead = null;
    }
  }
}
async function loadNodes(): Promise<void> {
  if (!auth.can("nodes")) return;
  const version = ++nodeVersion;
  nodeRead?.abort();
  const read = new AbortController();
  nodeRead = read;
  nodeLoading.value = true;
  nodeError.value = "";
  try {
    const result = await request<ManagedNodePage>(
      `/v1/nodes?${query({q: nodeQuery.value, page: nodePage.value, page_size: 20})}`,
      "GET",
      undefined,
      {signal: read.signal},
    );
    if (!alive || version !== nodeVersion) return;
    nodes.value = result.items;
    nodeTotal.value = result.count;
    nodePages.value = Math.max(1, Math.ceil(result.count / result.page_size));
  } catch (cause) {
    if (alive && version === nodeVersion && !read.signal.aborted) {
      nodeError.value = cause instanceof Error ? cause.message : t("dashboard.listError");
    }
  } finally {
    if (alive && version === nodeVersion) {
      nodeLoading.value = false;
      nodeRead = null;
    }
  }
}
async function load(): Promise<void> {
  loading.value = true;
  await Promise.all([loadCustomers(), loadNodes()]);
  loading.value = false;
}
watch(customerQuery, () => {
  customerPage.value = 1;
  if (customerTimer) clearTimeout(customerTimer);
  customerTimer = setTimeout(() => void loadCustomers(), 250);
});
watch(nodeQuery, () => {
  nodePage.value = 1;
  if (nodeTimer) clearTimeout(nodeTimer);
  nodeTimer = setTimeout(() => void loadNodes(), 250);
});
onMounted(load);
onUnmounted(() => {
  alive = false;
  ++customerVersion;
  ++nodeVersion;
  if (customerTimer) clearTimeout(customerTimer);
  if (nodeTimer) clearTimeout(nodeTimer);
  customerRead?.abort();
  nodeRead?.abort();
});
</script>
<template>
 <div class="page-head"><div><p class="eyebrow">{{t('dashboard.eyebrow')}}</p><h1>{{t('dashboard.title')}}</h1></div><button class="btn secondary" :disabled="loading" @click="load"><Icon name="grid" :size="16" />{{t('dashboard.refresh')}}</button></div>
 <section class="dashboard-hero"><div><p class="hero-kicker">{{t('dashboard.heroKicker')}}</p><h2>{{t('dashboard.heroTitle')}}</h2><p>{{t('dashboard.heroDescription')}}</p></div><div class="hero-brand" aria-hidden="true"><img class="papilio-logo papilio-logo-dark" src="/papilio-logo-dark.png" width="636" height="256" alt="" /><img class="papilio-logo papilio-logo-light" src="/papilio-logo-light.png" width="636" height="256" alt="" /></div></section>
 <section v-if="auth.can('customers')||auth.can('nodes')" class="card card-pad unified-records">
  <p class="eyebrow">{{t('dashboard.unifiedKicker')}}</p>
  <h2>{{t('dashboard.unifiedTitle')}}</h2>
  <div class="unified-record-grid">
   <section v-if="auth.can('customers')" class="record-panel">
    <div class="record-heading">
     <h3>{{t('dashboard.customerList')}}</h3>
    </div>
    <label class="field">
     <span>{{t('dashboard.searchCustomers')}}</span>
     <input v-model="customerQuery" :placeholder="t('dashboard.searchCustomersPlaceholder')" />
    </label>
    <p v-if="customerError" class="message error" role="alert">{{customerError}}</p>
    <div class="table-wrap">
     <table class="data-table">
      <thead><tr><th>{{t('dashboard.customerName')}}</th><th>{{t('dashboard.customerId')}}</th></tr></thead>
      <tbody>
       <tr v-for="row in customers" :key="row.id">
        <td><strong>{{row.name}}</strong></td>
        <td class="mono">{{row.id}}</td>
       </tr>
      </tbody>
     </table>
     <div v-if="customerLoading" class="empty">{{t('dashboard.listLoading')}}</div>
     <div v-else-if="!customers.length&&!customerError" class="empty">{{t('dashboard.noCustomers')}}</div>
    </div>
    <div class="pager">
     <button :disabled="customerLoading||customerPage<=1" :aria-label="t('dashboard.previousCustomerPage')" @click="customerPage--;loadCustomers()">‹</button>
     <span>{{t('dashboard.listPage',{page:faNumber(customerPage),total:faNumber(customerTotal)})}}</span>
     <button :disabled="customerLoading||customerPage>=customerPages" :aria-label="t('dashboard.nextCustomerPage')" @click="customerPage++;loadCustomers()">›</button>
    </div>
   </section>
   <section v-if="auth.can('nodes')" class="record-panel">
    <div class="record-heading">
     <h3>{{t('dashboard.serverList')}}</h3>
      <RouterLink class="btn small secondary" to="/nodes">{{t('dashboard.openServers')}}</RouterLink>
    </div>
    <label class="field">
     <span>{{t('dashboard.searchServers')}}</span>
     <input v-model="nodeQuery" :placeholder="t('dashboard.searchServersPlaceholder')" />
    </label>
    <p v-if="nodeError" class="message error" role="alert">{{nodeError}}</p>
    <div class="table-wrap">
     <table class="data-table">
      <thead><tr><th>{{t('dashboard.serverName')}}</th><th>{{t('dashboard.serverAddress')}}</th><th>{{t('dashboard.serverStatus')}}</th><th>{{t('nodes.connection')}}</th></tr></thead>
      <tbody>
       <tr v-for="row in nodes" :key="row.id">
        <td><RouterLink :to="`/nodes`"><strong>{{row.name}}</strong></RouterLink></td>
        <td dir="ltr">{{row.endpoint_url}}</td>
        <td>{{row.credentials_ready?t('nodes.credentialsReady'):t('nodes.credentialsPending')}}</td>
        <td><span class="badge" :class="row.last_reachable===true?'success':row.last_reachable===false?'warning':''">{{row.last_reachable===true?t('nodes.reachable'):row.last_reachable===false?t('nodes.unreachable'):t('nodes.unchecked')}}</span></td>
       </tr>
      </tbody>
     </table>
     <div v-if="nodeLoading" class="empty">{{t('dashboard.listLoading')}}</div>
     <div v-else-if="!nodes.length&&!nodeError" class="empty">{{t('dashboard.noServers')}}</div>
    </div>
    <div class="pager">
     <button :disabled="nodeLoading||nodePage<=1" :aria-label="t('dashboard.previousServerPage')" @click="nodePage--;loadNodes()">‹</button>
     <span>{{t('dashboard.listPage',{page:faNumber(nodePage),total:faNumber(nodeTotal)})}}</span>
     <button :disabled="nodeLoading||nodePage>=nodePages" :aria-label="t('dashboard.nextServerPage')" @click="nodePage++;loadNodes()">›</button>
    </div>
   </section>
  </div>
 </section>
 <div class="dashboard-grid"><section class="card card-pad"><p class="eyebrow">{{t('dashboard.actionsKicker')}}</p><h2>{{t('dashboard.actionsTitle')}}</h2><div class="action-grid">
  <RouterLink v-if="auth.can('nodes')" class="quick-link" to="/nodes"><span><Icon name="server" />{{t('dashboard.infrastructure')}}</span><Icon name="arrow" :size="17" /></RouterLink>
  <RouterLink v-if="auth.can('catalog')" class="quick-link" to="/plans"><span><Icon name="box" />{{t('dashboard.plans')}}</span><Icon name="arrow" :size="17" /></RouterLink>
  <RouterLink v-if="auth.can('payments')" class="quick-link" to="/payments"><span><Icon name="wallet" />{{t('dashboard.payments')}}</span><Icon name="arrow" :size="17" /></RouterLink>
  <RouterLink v-if="auth.can('customers')" class="quick-link" to="/customers"><span><Icon name="users" />{{t('dashboard.customers')}}</span><Icon name="arrow" :size="17" /></RouterLink>
 </div></section><section class="card card-pad"><p class="eyebrow">{{t('dashboard.workflowKicker')}}</p><h2>{{t('dashboard.workflowTitle')}}</h2>
  <div class="workflow-step"><span class="step-number">01</span><div><strong>{{t('dashboard.planStep')}}</strong><p>{{t('dashboard.planDescription')}}</p></div></div>
  <div class="workflow-step"><span class="step-number">02</span><div><strong>{{t('dashboard.paymentStep')}}</strong><p>{{t('dashboard.paymentDescription')}}</p></div></div>
  <div class="workflow-step"><span class="step-number">03</span><div><strong>{{t('dashboard.deliveryStep')}}</strong><p>{{t('dashboard.deliveryDescription')}}</p></div></div>
 </section></div>
</template>
