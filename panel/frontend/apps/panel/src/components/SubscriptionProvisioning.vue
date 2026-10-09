<script setup lang="ts">
import { ref, watch } from "vue";
import { item, query, request, type Page, type ProvisionRequest, type ProvisionTask } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faDate, faNumber } from "@papilio/ui";
const props = defineProps<{ subscriptionId: number }>();
const emit = defineEmits<{ changed: [] }>();
const auth = useAuth();
const rows = ref<ProvisionRequest[]>([]); const selected = ref<ProvisionRequest | null>(null); const tasks = ref<ProvisionTask[]>([]);
const page = ref(1); const pages = ref(1); const taskPage = ref(1); const taskPages = ref(1);
const loading = ref(false); const taskLoading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref(""); const reason = ref("");
let version = 0;
const labels: Record<string, string> = { queued: "Queued", awaiting_profiles: "Awaiting available configuration", dispatching: "Provisioning", active: "Active", attention: "Needs review", revoking: "Revoking on nodes", refunded: "Refunded", leased: "Sent to node", applied: "Applied", failed: "Attempt Failed", revoked: "Access revoked" };
const reasons: Record<string, string> = { no_enabled_targets: "No active configuration is available in the delivery group or assigned profiles.", target_capacity: "Configuration count exceeds the configured capacity.", provision_timeout: "Deadline or attempt limit reached.", expired_before_activation: "Subscription expired before delivery." };
async function load(): Promise<void> {
  const id = props.subscriptionId; const read = ++version; loading.value = true; error.value = "";
  try { const result = await request<Page<ProvisionRequest>>(`/v1/admin/provisioning?${query({ subscription_id: id, page: page.value })}`); if (id !== props.subscriptionId || read !== version) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; if (selected.value) selected.value = rows.value.find(row => row.id === selected.value?.id) ?? selected.value; }
  catch (cause) { if (read === version) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (read === version) loading.value = false; }
}
async function choose(row: ProvisionRequest): Promise<void> { if (busy.value) return; selected.value = row; taskPage.value = 1; reason.value = ""; await loadTasks(); }
async function loadTasks(): Promise<void> {
  if (!selected.value) return; const id = selected.value.id; const subscription = props.subscriptionId; const requested = taskPage.value; taskLoading.value = true; error.value = "";
  try { const result = await request<Page<ProvisionTask>>(`/v1/admin/provisioning/${id}/tasks?${query({ page: requested })}`); if (subscription !== props.subscriptionId || id !== selected.value?.id || requested !== taskPage.value) return; tasks.value = result.data; taskPages.value = result.meta.pager?.total_pages ?? 1; }
  catch (cause) { if (id === selected.value?.id && subscription === props.subscriptionId) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (id === selected.value?.id && subscription === props.subscriptionId) taskLoading.value = false; }
}
async function perform(action: "prepare" | "retry"): Promise<void> {
  const row = selected.value; if (!row) return; const subscription = props.subscriptionId; busy.value = true; error.value = ""; notice.value = "";
  try { const result = await item<ProvisionRequest>(`/v1/admin/provisioning/${row.id}/${action}`, "POST", action === "retry" ? { reason: reason.value.trim() } : undefined); if (subscription !== props.subscriptionId) return; selected.value = result; notice.value = action === "retry" ? "Retry recorded without another wallet charge." : "Node tasks prepared. Activation requires node confirmation."; emit("changed"); await load(); await loadTasks(); }
  catch (cause) { if (subscription === props.subscriptionId) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (subscription === props.subscriptionId) busy.value = false; }
}
watch(() => props.subscriptionId, () => { version++; rows.value = []; tasks.value = []; selected.value = null; page.value = 1; taskPage.value = 1; busy.value = false; notice.value = ""; void load(); }, { immediate: true });
</script>
<template>
  <h2>Provisioning and delivery</h2>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <button class="btn secondary" :disabled="busy" @click="load(); loadTasks()">Refresh provisioning</button>
  <p v-if="loading">Loading requests…</p><p v-else-if="!rows.length && !error">This subscription uses the legacy provisioning workflow. No requests recorded.</p>
  <div class="table-wrap"><table v-if="rows.length" class="data-table"><thead><tr><th>Request</th><th>Period</th><th>Deadline</th><th>Status</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="choose(row)" @keydown.enter="choose(row)"><td>{{ faNumber(row.id) }}</td><td>{{ faNumber(row.generation) }}</td><td>{{ faDate(row.deadline_at) }}</td><td>{{ labels[row.state] ?? 'Unknown status' }}</td></tr></tbody></table></div>
  <div class="pager"><button :disabled="page <= 1 || loading" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages || loading" @click="page++; load()">›</button></div>
  <section v-if="selected" class="form-grid">
    <p v-if="selected.reason_code" class="hint-box">{{ reasons[selected.reason_code] ?? 'Review node state before proceeding.' }}</p>
    <dl><dt>Activation requirement</dt><dd>{{ selected.policy.activation === 'all' ? 'All configurations' : selected.policy.activation === 'any' ? 'One configuration' : 'Quorum: ' + faNumber(selected.policy.minimum_successes) }}</dd><dt>Attempts and task lease</dt><dd>{{ faNumber(selected.policy.max_attempts) }} attempts · {{ faNumber(selected.policy.claim_seconds) }} seconds</dd><dt>Failure handling</dt><dd>{{ selected.policy.failure_action === 'hold' ? 'Operator review' : 'Revoke and refund wallet' }}</dd></dl>
    <template v-if="auth.can('subscriptions', 'create') && !['refunded', 'revoking', 'revoked'].includes(selected.state)">
      <button v-if="['queued', 'awaiting_profiles'].includes(selected.state)" class="btn" :disabled="busy" @click="perform('prepare')">Prepare node tasks</button>
      <label class="field"><span>Reason Retry</span><textarea v-model="reason" minlength="3" maxlength="250" /></label>
      <button class="btn secondary" :disabled="busy || reason.trim().length < 3" @click="perform('retry')">Retry without charging</button>
    </template>
    <p v-if="selected.state === 'revoking'" class="hint-box">{{ selected.completion === 'refund' ? 'Refund follows access revocation confirmation from every target node.' : 'All assigned nodes must revoke access at the end of the period. Period completion does not refund the purchase.' }}</p>
    <p v-if="taskLoading">Loading node tasks…</p>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Node</th><th>Configuration</th><th>Actions</th><th>Status</th><th>Attempt</th></tr></thead><tbody><tr v-for="task in tasks" :key="task.id"><td>{{ faNumber(task.node_id) }}</td><td>{{ faNumber(task.configuration_id) }}</td><td>{{ task.action === 'apply' ? 'Apply access' : 'Revoke access' }}</td><td>{{ labels[task.state] ?? 'Unknown status' }}<small v-if="task.error_code"> · Node error</small></td><td>{{ faNumber(task.attempts) }}</td></tr></tbody></table></div>
    <div class="pager"><button :disabled="taskPage <= 1 || taskLoading" @click="taskPage--; loadTasks()">‹</button><span>{{ faNumber(taskPage) }}</span><button :disabled="taskPage >= taskPages || taskLoading" @click="taskPage++; loadTasks()">›</button></div>
  </section>
</template>
