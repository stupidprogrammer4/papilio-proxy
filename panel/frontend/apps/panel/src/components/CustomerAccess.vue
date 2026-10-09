<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { item, request, query, ApiError, type Customer, type CustomerAccessState, type CustomerAccessChange, type Page } from "@papilio/api";
import { useAuth, useResellerAuth } from "@papilio/auth";
import { faDate, faNumber } from "@papilio/ui";
const props = defineProps<{ customer: Customer; realm?: "admin" | "reseller"; policyAllows?: boolean }>();
const emit = defineEmits<{ changed: [Customer] }>();
const auth = useAuth(), reseller = useResellerAuth();
const base = computed(() => props.realm === "reseller" ? "/v1/reseller/customers" : "/v1/admin/customers");
const canUpdate = computed(() => props.realm === "reseller" ? reseller.can("customers", "update") && props.policyAllows === true : auth.can("customers", "update"));
const draft = ref<CustomerAccessState | null>(null); const expected = ref<CustomerAccessState | null>(null);
const reason = ref(""); const clock = ref<"" | "pause" | "continue">(""); const key = ref("");
const busy = ref(false); const error = ref(""); const notice = ref("");
const history = ref<CustomerAccessChange[]>([]); const page = ref(1); const pages = ref(1); const historyState = ref<"loading" | "ready" | "error">("loading");
let version = 0;
function state(row: Customer): CustomerAccessState { return { is_active: row.is_active, services_enabled: row.services_enabled, renewals_enabled: row.renewals_enabled }; }
async function loadHistory(): Promise<void> {
  const id = props.customer.id; const selectedPage = page.value; const generation = version;
  historyState.value = "loading";
  try { const result = await request<Page<CustomerAccessChange>>(`${base.value}/${id}/access-history?${query({ page: selectedPage })}`); if (generation !== version || selectedPage !== page.value) return; history.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; historyState.value = "ready"; }
  catch (cause) { if (generation !== version) return; historyState.value = "error"; error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
watch(() => props.customer.id, () => { version++; draft.value = state(props.customer); expected.value = state(props.customer); clock.value = props.customer.service_hold_clock ?? ""; reason.value = ""; key.value = ""; error.value = ""; notice.value = ""; page.value = 1; history.value = []; void loadHistory(); }, { immediate: true });
watch(draft, () => { key.value = ""; }, { deep: true }); watch([reason, clock], () => { key.value = ""; });
async function save(): Promise<void> {
  if (!draft.value || !expected.value || busy.value) return;
  const id = props.customer.id; const generation = version;
  busy.value = true; error.value = ""; notice.value = ""; key.value ||= crypto.randomUUID();
  try {
    const row = await item<Customer>(`${base.value}/${id}/access`, "PUT", { request_key: key.value, expected: expected.value, values: draft.value, reason: reason.value.trim(), clock: draft.value.services_enabled ? null : clock.value });
    if (generation !== version) return;
    expected.value = state(row); draft.value = state(row); key.value = ""; reason.value = ""; emit("changed", row); notice.value = "Access saved. Suspended subscriptions need a separate resume action."; page.value = 1; await loadHistory();
  } catch (cause) {
    if (generation !== version) return; error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again.";
    if (cause instanceof ApiError && cause.code === "customer_access_changed") {
      try { const row = await item<Customer>(`${base.value}/${id}`); if (generation !== version) return; expected.value = state(row); emit("changed", row); key.value = ""; error.value += " Current record loaded; your selections are retained. Review before retrying."; }
      catch (refreshError) { error.value = refreshError instanceof Error ? refreshError.message : "Could not load the current record."; }
    }
  } finally { busy.value = false; }
}
</script>
<template>
  <section class="card card-pad"><h2>Customer access</h2><p>Sign-in, service and renewal access are independent. Suspension waits for node revocation confirmation. Enabling service access does not automatically resume subscriptions.</p><p v-if="customer.service_hold_pending" class="message" role="status">Service suspension awaits final usage and node revocation confirmation.</p><p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <form v-if="draft" class="form-grid" @submit.prevent="save"><fieldset :disabled="busy || !canUpdate"><label class="check-row"><input v-model="draft.is_active" type="checkbox" />Allow account sign-in</label><label class="check-row"><input v-model="draft.services_enabled" type="checkbox" />Allow purchases and service access</label><label class="check-row"><input v-model="draft.renewals_enabled" type="checkbox" />Automatic renewal access</label><label v-if="!draft.services_enabled" class="field"><span>Subscription clock during suspension</span><select aria-label="Subscription clock during suspension" v-model="clock" required><option value="" disabled>Select an option</option><option value="continue">Keep expiry clock running</option><option value="pause">Pause expiry clock</option></select></label><label class="field"><span>Access change reason</span><textarea v-model="reason" required minlength="3" maxlength="250" /></label><button v-if="canUpdate" class="btn" :disabled="busy || reason.trim().length < 3 || (!draft.services_enabled && !clock)">Save access</button></fieldset></form>
  <h3>Access history</h3><button class="btn secondary" :disabled="historyState === 'loading'" @click="loadHistory">Download History</button><p v-if="historyState === 'loading'">Loading…</p><p v-else-if="historyState === 'error'">Could not load history.</p><p v-else-if="!history.length">No changes recorded.</p><details v-for="row in history" :key="row.id"><summary>{{ faDate(row.created_at) }} · {{ row.staff_id !== null ? 'Operator ' + faNumber(row.staff_id) : 'Reseller member ' + faNumber(row.actor_account_id) }}</summary><p>{{ row.reason }}</p><p>Sign in: {{ row.values.is_active ? 'Enabled' : 'Inactive' }} · Service: {{ row.values.services_enabled ? 'Enabled' : 'Paused' }} · Renewal: {{ row.values.renewals_enabled ? 'Enabled' : 'Paused' }}</p><p v-if="row.clock">Clock: {{ row.clock === 'pause' ? 'Paused' : 'Continue' }}</p></details><div class="pager"><button :disabled="page <= 1" @click="page--; loadHistory()">‹</button><span>{{ faNumber(page) }} of {{ faNumber(pages) }}</span><button :disabled="page >= pages" @click="page++; loadHistory()">›</button></div></section>
</template>
<style scoped>fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: 14px; }</style>
