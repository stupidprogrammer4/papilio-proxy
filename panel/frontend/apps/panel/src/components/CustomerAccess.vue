<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { computed, ref, watch } from "vue";
import { item, request, query, ApiError, type Customer, type CustomerAccessState, type CustomerAccessChange, type Page } from "@papilio/api";
import { useAuth, useResellerAuth } from "@papilio/auth";
import { faDate, faNumber } from "@papilio/ui";
import {useI18n} from "vue-i18n";
const props = defineProps<{ customer: Customer; realm?: "admin" | "reseller"; policyAllows?: boolean }>();
const emit = defineEmits<{ changed: [Customer] }>();
const {t}=useI18n();
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
  busy.value = true; error.value = ""; notice.value = ""; key.value ||= newRequestKey();
  try {
    const row = await item<Customer>(`${base.value}/${id}/access`, "PUT", { request_key: key.value, expected: expected.value, values: draft.value, reason: reason.value.trim(), clock: draft.value.services_enabled ? null : clock.value });
    if (generation !== version) return;
    expected.value = state(row); draft.value = state(row); key.value = ""; reason.value = ""; emit("changed", row); notice.value = t("customerAccess.saved"); page.value = 1; await loadHistory();
  } catch (cause) {
    if (generation !== version) return; error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again.";
    if (cause instanceof ApiError && cause.code === "customer_access_changed") {
      try { const row = await item<Customer>(`${base.value}/${id}`); if (generation !== version) return; expected.value = state(row); emit("changed", row); key.value = ""; error.value += ` ${t("customerAccess.conflict")}`; }
      catch (refreshError) { error.value = refreshError instanceof Error ? refreshError.message : "Could not load the current record."; }
    }
  } finally { busy.value = false; }
}
</script>
<template>
  <section class="card card-pad"><h2>{{t('customerAccess.title')}}</h2><p>{{t('customerAccess.description')}}</p><p v-if="customer.service_hold_pending" class="message" role="status">{{t('customerAccess.pending')}}</p><p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <form v-if="draft" class="form-grid" @submit.prevent="save"><fieldset :disabled="busy || !canUpdate"><label class="check-row"><input v-model="draft.is_active" type="checkbox" />{{t('customerAccess.signin')}}</label><label class="check-row"><input v-model="draft.services_enabled" type="checkbox" />{{t('customerAccess.services')}}</label><label class="check-row"><input v-model="draft.renewals_enabled" type="checkbox" />{{t('customerAccess.renewals')}}</label><label v-if="!draft.services_enabled" class="field"><span>{{t('customerAccess.clock')}}</span><select :aria-label="t('customerAccess.clock')" v-model="clock" required><option value="" disabled>{{t('customerAccess.choose')}}</option><option value="continue">{{t('customerAccess.continue')}}</option><option value="pause">{{t('customerAccess.pause')}}</option></select></label><label class="field"><span>{{t('customerAccess.reason')}}</span><textarea v-model="reason" required minlength="3" maxlength="250" /></label><button v-if="canUpdate" class="btn" :disabled="busy || reason.trim().length < 3 || (!draft.services_enabled && !clock)">{{t('customerAccess.save')}}</button></fieldset></form>
  <h3>{{t('customerAccess.history')}}</h3><button class="btn secondary" :disabled="historyState === 'loading'" @click="loadHistory">{{t('customerAccess.download')}}</button><p v-if="historyState === 'loading'">{{t('customerAccess.loading')}}</p><p v-else-if="historyState === 'error'">{{t('customerAccess.error')}}</p><p v-else-if="!history.length">{{t('customerAccess.empty')}}</p><details v-for="row in history" :key="row.id"><summary>{{ faDate(row.created_at) }} · {{ row.staff_id !== null ? t('customerAccess.operator') + ' ' + faNumber(row.staff_id) : t('customerAccess.reseller') + ' ' + faNumber(row.actor_account_id) }}</summary><p>{{ row.reason }}</p><p>{{t('customerAccess.signIn')}}: {{ row.values.is_active ? t('customerAccess.enabled') : t('customerAccess.inactive') }} · {{t('customerAccess.service')}}: {{ row.values.services_enabled ? t('customerAccess.enabled') : t('customerAccess.paused') }} · {{t('customerAccess.renewal')}}: {{ row.values.renewals_enabled ? t('customerAccess.enabled') : t('customerAccess.paused') }}</p><p v-if="row.clock">{{t('customerAccess.clockLabel')}}: {{ row.clock === 'pause' ? t('customerAccess.pause') : t('customerAccess.continue') }}</p></details><div class="pager"><button :disabled="page <= 1" @click="page--; loadHistory()">‹</button><span>{{t('customerAccess.of',{page:faNumber(page),pages:faNumber(pages)})}}</span><button :disabled="page >= pages" @click="page++; loadHistory()">›</button></div></section>
</template>
<style scoped>fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: 14px; }</style>
