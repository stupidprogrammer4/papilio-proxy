<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useAuth } from "@papilio/auth";
import { request, type AutomationSchedule } from "@papilio/api";
import { faDigits, faNumber } from "@papilio/ui";
import ScheduleEditor from "../components/automation/ScheduleEditor.vue";
import PaymentReviews from "../components/automation/PaymentReviews.vue";
import NodeHealthChecks from "../components/automation/NodeHealthChecks.vue";
import SubscriptionAttentionChecks from "../components/automation/SubscriptionAttentionChecks.vue";
const auth = useAuth();
const { t } = useI18n();
const selected = ref<AutomationSchedule|null>(null);
function scheduleChanged(row: AutomationSchedule): void { schedules.value=schedules.value.map(current=>current.key===row.key?row:current); if(selected.value?.key===row.key) selected.value=row; }
const schedules = ref<AutomationSchedule[]>([]); const loading = ref(false); const error = ref("");
const titles: Record<string, string> = { core_runtime: "Core command recovery", core_provisioning: "Automatic core provisioning", customer_holds: "Customer service holds", provisioning: "Service provisioning", lifecycle: "Expiry and quota enforcement", payments: "Payment reconciliation", nodes: "Node health", attention: "Subscription alerts", renewals: "Renewal Automatic", notifications: "Notification delivery" };
function scheduleTitle(key: string): string {
  const translationKey = `automation.jobs.${key}`;
  const translated = t(translationKey);
  return translated === translationKey ? titles[key] ?? t("automation.actions") : translated;
}
async function load(): Promise<void> {
  loading.value = true; error.value = "";
  try { const result = await request<{ data: AutomationSchedule[] }>("/v1/admin/automation/schedules"); schedules.value = result.data; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { loading.value = false; }
}
onMounted(load);
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">{{ t('automation.eyebrow') }}</p><h1>{{ t('automation.title') }}</h1><p class="subtitle">{{ t('automation.description') }}</p></div></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p>
  <div class="card card-pad" style="margin-bottom:18px"><h2>{{ t('automation.schedulesTitle') }}</h2><p v-if="loading">{{ t('automation.loading') }}</p><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t('automation.actions') }}</th><th>{{ t('automation.status') }}</th><th>{{ t('automation.schedule') }}</th><th>{{ t('automation.recordsPerRun') }}</th><th>{{ t('automation.recheckInterval') }}</th></tr></thead><tbody><tr v-for="job in schedules" :key="job.key" tabindex="0" :class="{'selected-row': selected?.key === job.key}" @click="selected = job" @keydown.enter="selected = job"><td>{{ scheduleTitle(job.key) }}</td><td>{{ !job.capacity_valid ? t('automation.capacityPaused') : job.enabled ? t('automation.active') : t('automation.paused') }} · {{ job.applied_revision === job.revision ? t('automation.registered') : t('automation.awaitingReconciliation') }}</td><td class="mono" dir="ltr">{{ job.mode === 'interval' ? faNumber(job.interval_seconds ?? 0) + ' ' + t('automation.seconds') : faDigits(job.cron ?? '') + ' · ' + job.timezone }}</td><td class="tabular">{{ faNumber(job.batch_size) }}</td><td class="tabular">{{ job.recheck_seconds === null ? t('automation.expiryDriven') : faNumber(job.recheck_seconds) + ' ' + t('automation.seconds') }}</td></tr></tbody></table></div></div>
  <ScheduleEditor v-if="selected" :schedule="selected" :title="scheduleTitle(selected.key)" @changed="scheduleChanged" />
  <div class="stack"><PaymentReviews v-if="auth.can('payments')" /><NodeHealthChecks v-if="auth.can('network')" /><SubscriptionAttentionChecks v-if="auth.can('subscriptions')" /></div>
</template>
