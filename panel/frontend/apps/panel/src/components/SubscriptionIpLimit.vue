<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { item, query, request, type IpLimitDetail, type IpLimitPolicy, type IpPolicyTransitionRead, type IpSession, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faDate, faNumber } from "@papilio/ui";
import NumField from "@papilio/ui/NumField.vue";
import { ipAllowanceText } from "./ipLimits/policy";
import IpPolicyTransition from "./ipLimits/IpPolicyTransition.vue";

const props = defineProps<{ subscriptionId: number }>();
const emit = defineEmits<{ changed: [] }>();
const auth = useAuth();
const detail = ref<IpLimitDetail | null>(null);
const rows = ref<IpSession[]>([]);
const selected = ref<IpSession | null>(null);
const page = ref(1); const pages = ref(1); const total = ref(0);
const search = ref(""); const state = ref("");
const loading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref("");
const banSeconds = ref(""); const banReason = ref("");
const choice = reactive({ enabled: false, max_ips: "", lease_seconds: "", ban_seconds: "", mode: "reject_new" as IpLimitPolicy["mode"] });
const transitionMode = ref<IpPolicyTransitionRead["mode"] | "">("");
const transitionAvailable = computed(() => !detail.value?.transition_options || detail.value.transition_options.choices.some(option => option.mode === transitionMode.value && option.available));
const transitionLabels: Record<IpPolicyTransitionRead["mode"], string> = { drain_leases: "Wait for issued leases to expire", require_closed_receipts: "Require verified connection-closure receipts" };
let readVersion = 0;
const base = computed(() => `/v1/admin/subscriptions/${props.subscriptionId}/ip-limit`);
const admissionPolicy = computed(() => detail.value?.effective_ip_policy !== undefined ? detail.value.effective_ip_policy.policy : detail.value?.policy ?? null);
const admissionAllowance = computed(() => admissionPolicy.value ? ipAllowanceText(admissionPolicy.value) : detail.value?.effective_ip_policy !== undefined ? "No recorded source-IP restriction" : "Allowance unavailable from this API");
const admissionSource = computed(() => {
  const source = detail.value?.effective_ip_policy?.source;
  if (source === "subscription_override") return "Recorded operational policy";
  if (source === "purchased_snapshot") return "Purchased snapshot";
  if (source === "legacy_unrestricted") return "Legacy: no recorded restriction";
  return detail.value?.policy ? "Recorded operational policy; effective projection unavailable" : "Effective projection unavailable";
});
const reasons: Record<string, string> = { ip_limit_exceeded: "IP limit exceeded", replaced_oldest: "Oldest IP replaced" };

function fill(value: IpLimitDetail): void {
  const effective = value.effective_ip_policy?.policy;
  const policy = value.policy ?? effective ?? value.defaults;
  choice.enabled = value.policy?.enabled ?? effective?.enabled ?? false;
  choice.max_ips = String(policy.max_ips); choice.lease_seconds = String(policy.lease_seconds); choice.ban_seconds = String(policy.ban_seconds);
  choice.mode = policy.mode;
  transitionMode.value = value.effective_ip_policy?.transition?.mode ?? value.transition_options?.default_mode ?? "";
  banSeconds.value = String(policy.ban_seconds);
}
async function load(includePolicy = false): Promise<void> {
  includePolicy ||= detail.value === null;
  const id = props.subscriptionId; const version = ++readVersion;
  loading.value = true; error.value = "";
  try {
    const [policy, result] = await Promise.all([
      includePolicy ? item<IpLimitDetail>(base.value) : Promise.resolve(null),
      request<Page<IpSession>>(`${base.value}/sessions?${query({ page: page.value, state: state.value || undefined, q: search.value || undefined })}`),
    ]);
    if (version !== readVersion || id !== props.subscriptionId) return;
    if (policy) { detail.value = policy; fill(policy); }
    rows.value = result.data; total.value = result.meta.pager?.total_items ?? 0; pages.value = result.meta.pager?.total_pages ?? 1;
    if (selected.value) selected.value = rows.value.find(row => row.id === selected.value?.id) ?? selected.value;
  } catch (cause) { if (version === readVersion && id === props.subscriptionId) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (version === readVersion) loading.value = false; }
}
async function save(): Promise<void> {
  if (!transitionAvailable.value) return;
  const id = props.subscriptionId; busy.value = true; error.value = ""; notice.value = "";
  try {
    await item<IpLimitPolicy>(base.value, "PUT", { enabled: choice.enabled, max_ips: Number(choice.max_ips), lease_seconds: Number(choice.lease_seconds), ban_seconds: Number(choice.ban_seconds), mode: choice.mode, ...(transitionMode.value ? { transition_mode: transitionMode.value } : {}) });
    if (id !== props.subscriptionId) return;
    await load(true);
    if (id !== props.subscriptionId || error.value) return;
    notice.value = detail.value?.effective_ip_policy?.transition ? "Requested policy saved. Activation is pending; the current recorded allowance is unchanged." : "IP policy saved.";
    if (id === props.subscriptionId) emit("changed");
  } catch (cause) { if (id === props.subscriptionId) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (id === props.subscriptionId) busy.value = false; }
}
async function restrict(action: "ban" | "unban"): Promise<void> {
  const row = selected.value; if (!row) return;
  const id = props.subscriptionId; busy.value = true; error.value = ""; notice.value = "";
  try {
    const result = await item<IpSession>(`${base.value}/sessions/${row.id}/${action}`, "POST", action === "ban" ? { seconds: Number(banSeconds.value), reason: banReason.value.trim() } : undefined);
    if (id !== props.subscriptionId) return;
    if (selected.value?.id === row.id) selected.value = result;
    notice.value = action === "ban" ? "Timed IP ban recorded." : "Ban removed. The next admission depends on subscription capacity.";
    if (action === "ban") banReason.value = "";
    await load();
  } catch (cause) { if (id === props.subscriptionId) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (id === props.subscriptionId) busy.value = false; }
}
watch(() => props.subscriptionId, () => { ++readVersion; detail.value = null; rows.value = []; selected.value = null; page.value = 1; busy.value = false; notice.value = ""; banReason.value = ""; void load(true); }, { immediate: true });
watch([state, search], () => { page.value = 1; void load(); });
</script>
<template>
  <section class="form-grid" aria-label="Limit IP Subscription">
    <h2>Source IP admission</h2>
    <p class="subtitle">API admission decisions only. Core enforcement is not verified. Source IP counts do not represent device counts. One allowance applies to this subscription's configurations.</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
    <div v-if="detail" class="form-grid">
      <p class="message">Current API admission allowance: {{ admissionAllowance }}</p>
      <p class="subtitle">{{ admissionSource }}</p>
      <IpPolicyTransition v-if="detail.effective_ip_policy?.transition" :transition="detail.effective_ip_policy.transition" />
      <form v-if="auth.can('subscriptions', 'update')" class="form-grid" @submit.prevent="save"><p class="subtitle">This administrator override changes current admission decisions without rewriting purchased terms. Disabled means unlimited source IPs.</p>
        <p v-if="detail.effective_ip_policy?.transition" class="subtitle">Edit the requested policy below. Saving does not bypass the pending transition.</p>
        <label class="field"><span><input v-model="choice.enabled" type="checkbox" :disabled="busy" /> Limit concurrent source IPs (operational override)</span></label>
        <NumField v-model="choice.max_ips" label="Maximum concurrent IPs" />
        <NumField v-model="choice.lease_seconds" label="Activity window (seconds)" />
        <NumField v-model="choice.ban_seconds" label="Automatic ban duration (seconds)" />
        <label class="field"><span>Behavior at the limit</span><select v-model="choice.mode" aria-label="Behavior at the limit"><option value="reject_new">Reject new IP</option><option value="replace_oldest">Oldest IP replaced</option></select></label>
        <template v-if="detail.transition_options"><label class="field"><span>When tightening the allowance</span><select v-model="transitionMode" aria-label="When tightening the allowance"><option v-for="option in detail.transition_options.choices" :key="option.mode" :value="option.mode" :disabled="!option.available">{{transitionLabels[option.mode]}}{{option.available?'':' — unavailable'}}</option></select></label><p class="subtitle">Configured default: {{transitionLabels[detail.transition_options.default_mode]}}.</p><p v-if="!transitionAvailable" class="message">This transition method is unavailable. Choose an available method to save.</p></template>
        <button class="btn" :disabled="busy || loading || !transitionAvailable || !Number.isSafeInteger(Number(choice.max_ips)) || Number(choice.max_ips)<=0 || Number(choice.max_ips)>detail.defaults.max_ips_ceiling || !Number.isSafeInteger(Number(choice.lease_seconds)) || Number(choice.lease_seconds)<=0 || Number(choice.lease_seconds)>detail.defaults.max_lease_seconds || !Number.isSafeInteger(Number(choice.ban_seconds)) || Number(choice.ban_seconds)<=0 || Number(choice.ban_seconds)>detail.defaults.max_ban_seconds">Save IP policy</button>
      </form>
      <div v-else-if="admissionPolicy" class="detail-line"><span>IP allowance / activity window</span><strong>{{ ipAllowanceText(admissionPolicy) }} / {{ faNumber(admissionPolicy.lease_seconds) }} seconds</strong></div>
    </div>
    <div class="toolbar"><label class="field"><span>Search IPs</span><input v-model="search" type="search" dir="ltr" aria-label="Search IPs" /></label><label class="field"><span>Status IP</span><select v-model="state" aria-label="Status IP"><option value="">All</option><option value="active">Active</option><option value="blocked">Blocked</option><option value="inactive">Inactive</option></select></label><button class="btn secondary" :disabled="loading" @click="load(true)">Refresh IPs</button></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>IP</th><th>Last node</th><th>Activity expires</th><th>Ban expires</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="selected = row" @keydown.enter="selected = row"><td dir="ltr">{{ row.source_ip }}</td><td>{{ faNumber(row.last_node_id) }}</td><td>{{ faDate(row.expires_at) }}</td><td>{{ row.blocked_until ? faDate(row.blocked_until) : '—' }}</td></tr></tbody></table></div>
    <p v-if="loading" class="empty">Loading IPs…</p><p v-else-if="!error && !rows.length" class="empty">No IP records match this filter.</p>
    <div class="pager"><button :disabled="page <= 1 || loading" @click="page--; load()">‹</button><span>Page {{ faNumber(page) }} · {{ faNumber(total) }} IP</span><button :disabled="page >= pages || loading" @click="page++; load()">›</button></div>
    <div v-if="selected" class="form-grid"><h3 dir="ltr">{{ selected.source_ip }}</h3><p v-if="selected.block_reason" class="message">{{ reasons[selected.block_reason] ?? selected.block_reason }}</p><template v-if="auth.can('subscriptions', 'update')"><NumField v-model="banSeconds" label="Ban duration (seconds)" /><label class="field"><span>Ban reason</span><textarea v-model="banReason" minlength="3" maxlength="250" /></label><div class="toolbar"><button class="btn danger" :disabled="busy || Number(banSeconds) <= 0 || banReason.trim().length < 3" @click="restrict('ban')">Ban selected IP</button><button class="btn secondary" :disabled="busy" @click="restrict('unban')">Unban selected IP</button></div></template></div>
  </section>
</template>
