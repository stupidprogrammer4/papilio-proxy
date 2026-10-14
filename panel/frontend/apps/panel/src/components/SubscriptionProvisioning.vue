<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { item, query, request, type Page, type ProvisionRequest, type ProvisionTask } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faDate, faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";
const props = defineProps<{ subscriptionId: number }>();
const { t } = useI18n();
const emit = defineEmits<{ changed: [] }>();
const auth = useAuth();
const rows = ref<ProvisionRequest[]>([]); const selected = ref<ProvisionRequest | null>(null); const tasks = ref<ProvisionTask[]>([]);
const page = ref(1); const pages = ref(1); const taskPage = ref(1); const taskPages = ref(1);
const loading = ref(false); const taskLoading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref(""); const reason = ref("");
let version = 0;
const labels = computed<Record<string, string>>(() => ({ queued: t("subscriptionProvisioning.states.queued"), awaiting_profiles: t("subscriptionProvisioning.states.awaitingProfiles"), dispatching: t("subscriptionProvisioning.states.dispatching"), active: t("subscriptionProvisioning.states.active"), attention: t("subscriptionProvisioning.states.attention"), revoking: t("subscriptionProvisioning.states.revoking"), refunded: t("subscriptionProvisioning.states.refunded"), leased: t("subscriptionProvisioning.states.leased"), applied: t("subscriptionProvisioning.states.applied"), failed: t("subscriptionProvisioning.states.failed"), revoked: t("subscriptionProvisioning.states.revoked") }));
const reasons = computed<Record<string, string>>(() => ({ no_enabled_targets: t("subscriptionProvisioning.reasons.noEnabledTargets"), target_capacity: t("subscriptionProvisioning.reasons.targetCapacity"), provision_timeout: t("subscriptionProvisioning.reasons.timeout"), expired_before_activation: t("subscriptionProvisioning.reasons.expired") }));
async function load(): Promise<void> {
  const id = props.subscriptionId; const read = ++version; loading.value = true; error.value = "";
  try { const result = await request<Page<ProvisionRequest>>(`/v1/admin/provisioning?${query({ subscription_id: id, page: page.value })}`); if (id !== props.subscriptionId || read !== version) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; if (selected.value) selected.value = rows.value.find(row => row.id === selected.value?.id) ?? selected.value; }
  catch (cause) { if (read === version) error.value = cause instanceof Error ? cause.message : t("subscriptionProvisioning.operationFailed"); }
  finally { if (read === version) loading.value = false; }
}
async function choose(row: ProvisionRequest): Promise<void> { if (busy.value) return; selected.value = row; taskPage.value = 1; reason.value = ""; await loadTasks(); }
async function loadTasks(): Promise<void> {
  if (!selected.value) return; const id = selected.value.id; const subscription = props.subscriptionId; const requested = taskPage.value; taskLoading.value = true; error.value = "";
  try { const result = await request<Page<ProvisionTask>>(`/v1/admin/provisioning/${id}/tasks?${query({ page: requested })}`); if (subscription !== props.subscriptionId || id !== selected.value?.id || requested !== taskPage.value) return; tasks.value = result.data; taskPages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if (id === selected.value?.id && subscription === props.subscriptionId) error.value = cause instanceof Error ? cause.message : t("subscriptionProvisioning.operationFailed"); }
  finally { if (id === selected.value?.id && subscription === props.subscriptionId) taskLoading.value = false; }
}
async function perform(action: "prepare" | "retry"): Promise<void> {
  const row = selected.value; if (!row) return; const subscription = props.subscriptionId; busy.value = true; error.value = ""; notice.value = "";
  try { const result = await item<ProvisionRequest>(`/v1/admin/provisioning/${row.id}/${action}`, "POST", action === "retry" ? { reason: reason.value.trim() } : undefined); if (subscription !== props.subscriptionId) return; selected.value = result; notice.value = action === "retry" ? t("subscriptionProvisioning.retryRecorded") : t("subscriptionProvisioning.prepared"); emit("changed"); await load(); await loadTasks(); }
  catch (cause) { if (subscription === props.subscriptionId) error.value = cause instanceof Error ? cause.message : t("subscriptionProvisioning.operationFailed"); }
  finally { if (subscription === props.subscriptionId) busy.value = false; }
}
watch(() => props.subscriptionId, () => { version++; rows.value = []; tasks.value = []; selected.value = null; page.value = 1; taskPage.value = 1; busy.value = false; notice.value = ""; void load(); }, { immediate: true });
</script>
<template>
  <h2>{{ t('subscriptionProvisioning.title') }}</h2>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <button class="btn secondary" :disabled="busy" @click="load(); loadTasks()">{{ t('subscriptionProvisioning.refresh') }}</button>
  <p v-if="loading">{{ t('subscriptionProvisioning.loadingRequests') }}</p><p v-else-if="!rows.length && !error">{{ t('subscriptionProvisioning.legacyEmpty') }}</p>
  <div class="table-wrap"><table v-if="rows.length" class="data-table"><thead><tr><th>{{ t('subscriptionProvisioning.request') }}</th><th>{{ t('subscriptionProvisioning.generation') }}</th><th>{{ t('subscriptionProvisioning.deadline') }}</th><th>{{ t('subscriptionProvisioning.status') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="choose(row)" @keydown.enter="choose(row)"><td>{{ faNumber(row.id) }}</td><td>{{ faNumber(row.generation) }}</td><td>{{ faDate(row.deadline_at) }}</td><td>{{ labels[row.state] ?? t('subscriptionProvisioning.unknown') }}</td></tr></tbody></table></div>
  <div class="pager"><button :disabled="page <= 1 || loading" :aria-label="t('subscriptionProvisioning.previousPage')" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages || loading" :aria-label="t('subscriptionProvisioning.nextPage')" @click="page++; load()">›</button></div>
  <section v-if="selected" class="form-grid">
    <p v-if="selected.reason_code" class="hint-box">{{ reasons[selected.reason_code] ?? 'Review node state before proceeding.' }}</p>
    <dl><dt>{{ t('subscriptionProvisioning.activationRequirement') }}</dt><dd>{{ selected.policy.activation === 'all' ? t('subscriptionProvisioning.allConfigurations') : selected.policy.activation === 'any' ? t('subscriptionProvisioning.oneConfiguration') : t('subscriptionProvisioning.quorum', { count: faNumber(selected.policy.minimum_successes) }) }}</dd><dt>{{ t('subscriptionProvisioning.attemptsLease') }}</dt><dd>{{ t('subscriptionProvisioning.attemptsAndSeconds', { attempts: faNumber(selected.policy.max_attempts), seconds: faNumber(selected.policy.claim_seconds) }) }}</dd><dt>{{ t('subscriptionProvisioning.failureHandling') }}</dt><dd>{{ selected.policy.failure_action === 'hold' ? t('subscriptionProvisioning.operatorReview') : t('subscriptionProvisioning.revokeRefund') }}</dd></dl>
    <template v-if="auth.can('subscriptions', 'create') && !['refunded', 'revoking', 'revoked'].includes(selected.state)">
      <button v-if="['queued', 'awaiting_profiles'].includes(selected.state)" class="btn" :disabled="busy" @click="perform('prepare')">{{ t('subscriptionProvisioning.prepareTasks') }}</button>
      <label class="field"><span>{{ t('subscriptionProvisioning.retryReason') }}</span><textarea v-model="reason" minlength="3" maxlength="250" /></label>
      <button class="btn secondary" :disabled="busy || reason.trim().length < 3" @click="perform('retry')">{{ t('subscriptionProvisioning.retryWithoutCharge') }}</button>
    </template>
    <p v-if="selected.state === 'revoking'" class="hint-box">{{ selected.completion === 'refund' ? t('subscriptionProvisioning.refundAfterRevocation') : t('subscriptionProvisioning.periodRevocation') }}</p>
    <p v-if="taskLoading">{{ t('subscriptionProvisioning.loadingTasks') }}</p>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t('subscriptionProvisioning.node') }}</th><th>{{ t('subscriptionProvisioning.configuration') }}</th><th>{{ t('subscriptionProvisioning.taskAction') }}</th><th>{{ t('subscriptionProvisioning.status') }}</th><th>{{ t('subscriptionProvisioning.attempt') }}</th></tr></thead><tbody><tr v-for="task in tasks" :key="task.id"><td>{{ faNumber(task.node_id) }}</td><td>{{ faNumber(task.configuration_id) }}</td><td>{{ task.action === 'apply' ? t('subscriptionProvisioning.applyAccess') : t('subscriptionProvisioning.revokeAccess') }}</td><td>{{ labels[task.state] ?? t('subscriptionProvisioning.unknown') }}<small v-if="task.error_code"> · {{ t('subscriptionProvisioning.nodeError') }}</small></td><td>{{ faNumber(task.attempts) }}</td></tr></tbody></table></div>
    <div class="pager"><button :disabled="taskPage <= 1 || taskLoading" :aria-label="t('subscriptionProvisioning.previousPage')" @click="taskPage--; loadTasks()">‹</button><span>{{ faNumber(taskPage) }}</span><button :disabled="taskPage >= taskPages || taskLoading" :aria-label="t('subscriptionProvisioning.nextPage')" @click="taskPage++; loadTasks()">›</button></div>
  </section>
</template>
