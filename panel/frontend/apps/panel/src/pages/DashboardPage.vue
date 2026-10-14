<script setup lang="ts">
import {onMounted,ref} from "vue";
import { useI18n } from "vue-i18n";
import {request,type Page} from "@papilio/api";
import {faNumber} from "@papilio/ui";
import Icon from "@papilio/ui/Icon.vue";
import {useAuth} from "@papilio/auth";
const auth=useAuth();
const { t } = useI18n();
const loading=ref(false);
const metrics=ref([{title:"Customers",description:"Registered customer accounts",icon:"users",scope:"customers",path:"/v1/admin/customers?per_page=1",value:null as number|null,error:false},{title:"Payments to review",description:"Awaiting bank-verified approval",icon:"wallet",scope:"payments",path:"/v1/admin/payments/topups?status=pending&per_page=1",value:null as number|null,error:false},{title:"Pending delivery",description:"Subscriptions awaiting provisioning",icon:"link",scope:"subscriptions",path:"/v1/admin/subscriptions?status=pending_provision&per_page=1",value:null as number|null,error:false}]);
async function load():Promise<void>{loading.value=true;const visible=metrics.value.filter(row=>auth.can(row.scope));const outcomes=await Promise.allSettled(visible.map(row=>request<Page<unknown>>(row.path)));outcomes.forEach((result,index)=>{const metric=visible[index];if(!metric)return;metric.error=result.status==='rejected';metric.value=result.status==='fulfilled'?result.value.meta.pager?.total_items??0:null;});loading.value=false;}
onMounted(load);
</script>
<template>
 <div class="page-head"><div><p class="eyebrow">{{t('dashboard.eyebrow')}}</p><h1>{{t('dashboard.title')}}</h1></div><button class="btn secondary" :disabled="loading" @click="load"><Icon name="grid" :size="16" />{{t('dashboard.refresh')}}</button></div>
 <section class="dashboard-hero"><div><p class="hero-kicker">{{t('dashboard.heroKicker')}}</p><h2>{{t('dashboard.heroTitle')}}</h2><p>{{t('dashboard.heroDescription')}}</p></div><div class="hero-brand" aria-hidden="true"><img class="papilio-logo papilio-logo-dark" src="/papilio-logo-dark.png" width="636" height="256" alt="" /><img class="papilio-logo papilio-logo-light" src="/papilio-logo-light.png" width="636" height="256" alt="" /></div></section>
 <div class="stats"><article v-for="metric in metrics.filter(row=>auth.can(row.scope))" :key="metric.scope" class="stat"><div class="stat-head"><span class="label">{{t(`dashboard.metrics.${metric.scope}.title`)}}</span><span class="stat-icon"><Icon :name="metric.icon" :size="18" /></span></div><div class="value tabular">{{loading?'…':faNumber(metric.value)}}</div><p v-if="metric.error" class="message error" role="alert">{{t('dashboard.metricError')}}</p><div class="stat-footer"><span class="hint">{{t(`dashboard.metrics.${metric.scope}.description`)}}</span></div></article></div>
 <div class="dashboard-grid"><section class="card card-pad"><p class="eyebrow">{{t('dashboard.actionsKicker')}}</p><h2>{{t('dashboard.actionsTitle')}}</h2><div class="action-grid">
  <RouterLink v-if="auth.can('customers')" class="quick-link" to="/customers"><span><Icon name="users" />{{t('dashboard.customers')}}</span><Icon name="arrow" :size="17" /></RouterLink>
  <RouterLink v-if="auth.can('catalog')" class="quick-link" to="/plans"><span><Icon name="box" />{{t('dashboard.plans')}}</span><Icon name="arrow" :size="17" /></RouterLink>
  <RouterLink v-if="auth.can('payments')" class="quick-link" to="/payments"><span><Icon name="wallet" />{{t('dashboard.payments')}}</span><Icon name="arrow" :size="17" /></RouterLink>
  <RouterLink v-if="auth.can('network')" class="quick-link" to="/network"><span><Icon name="server" />{{t('dashboard.infrastructure')}}</span><Icon name="arrow" :size="17" /></RouterLink>
  <RouterLink v-if="['payments','network','subscriptions'].some(scope=>auth.can(scope))" class="quick-link" to="/automation"><span><Icon name="bolt" />{{t('dashboard.automation')}}</span><Icon name="arrow" :size="17" /></RouterLink>
 </div></section><section class="card card-pad"><p class="eyebrow">{{t('dashboard.workflowKicker')}}</p><h2>{{t('dashboard.workflowTitle')}}</h2>
  <div class="workflow-step"><span class="step-number">01</span><div><strong>{{t('dashboard.planStep')}}</strong><p>{{t('dashboard.planDescription')}}</p></div></div>
  <div class="workflow-step"><span class="step-number">02</span><div><strong>{{t('dashboard.paymentStep')}}</strong><p>{{t('dashboard.paymentDescription')}}</p></div></div>
  <div class="workflow-step"><span class="step-number">03</span><div><strong>{{t('dashboard.deliveryStep')}}</strong><p>{{t('dashboard.deliveryDescription')}}</p></div></div>
 </section></div>
</template>
