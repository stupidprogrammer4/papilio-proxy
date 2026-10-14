<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { item, query, request, type IpLimitChoice, type IpLimitDetail, type IpLimitPolicy, type IpPolicyTransitionRead, type IpSession, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faDate, faNumber } from "@papilio/ui";
import NumField from "@papilio/ui/NumField.vue";
import { ipAllowanceText } from "./ipLimits/policy";
import IpPolicyTransition from "./ipLimits/IpPolicyTransition.vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ subscriptionId: number }>();
const { t } = useI18n();
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
function allowance(policy: IpLimitChoice | null | undefined): string {
  return ipAllowanceText(policy, {
    none: t("ipPolicySummary.allowance.none"), unlimited: t("ipPolicySummary.allowance.unlimited"), invalid: t("ipPolicySummary.allowance.invalid"),
    one: t("ipPolicySummary.allowance.one"), many: count => t("ipPolicySummary.allowance.many", { count }),
  });
}
const transitionAvailable = computed(() => !detail.value?.transition_options || detail.value.transition_options.choices.some(option => option.mode === transitionMode.value && option.available));
const transitionLabels = computed<Record<IpPolicyTransitionRead["mode"], string>>(() => ({ drain_leases: t("subscriptionIpLimit.transition.drain"), require_closed_receipts: t("subscriptionIpLimit.transition.receipts") }));
let readVersion = 0;
const base = computed(() => `/v1/admin/subscriptions/${props.subscriptionId}/ip-limit`);
const admissionPolicy = computed(() => detail.value?.effective_ip_policy !== undefined ? detail.value.effective_ip_policy.policy : detail.value?.policy ?? null);
const admissionAllowance = computed(() => admissionPolicy.value ? allowance(admissionPolicy.value) : detail.value?.effective_ip_policy !== undefined ? t("subscriptionIpLimit.unrestricted") : t("subscriptionIpLimit.allowanceUnavailable"));
const admissionSource = computed(() => {
  const source = detail.value?.effective_ip_policy?.source;
  if (source === "subscription_override") return t("subscriptionIpLimit.operationalPolicy");
  if (source === "purchased_snapshot") return t("subscriptionIpLimit.purchasedSnapshot");
  if (source === "legacy_unrestricted") return t("subscriptionIpLimit.legacyUnrestricted");
  return detail.value?.policy ? t("subscriptionIpLimit.projectionFallback") : t("subscriptionIpLimit.projectionUnavailable");
});
const reasons = computed<Record<string, string>>(() => ({ ip_limit_exceeded: t("subscriptionIpLimit.reasons.limit"), replaced_oldest: t("subscriptionIpLimit.reasons.replaced") }));

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
  } catch (cause) { if (version === readVersion && id === props.subscriptionId) error.value = cause instanceof Error ? cause.message : t("subscriptionIpLimit.operationFailed"); }
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
    notice.value = detail.value?.effective_ip_policy?.transition ? t("subscriptionIpLimit.savedPending") : t("subscriptionIpLimit.saved");
    if (id === props.subscriptionId) emit("changed");
  } catch (cause) { if (id === props.subscriptionId) error.value = cause instanceof Error ? cause.message : t("subscriptionIpLimit.operationFailed"); }
  finally { if (id === props.subscriptionId) busy.value = false; }
}
async function restrict(action: "ban" | "unban"): Promise<void> {
  const row = selected.value; if (!row) return;
  const id = props.subscriptionId; busy.value = true; error.value = ""; notice.value = "";
  try {
    const result = await item<IpSession>(`${base.value}/sessions/${row.id}/${action}`, "POST", action === "ban" ? { seconds: Number(banSeconds.value), reason: banReason.value.trim() } : undefined);
    if (id !== props.subscriptionId) return;
    if (selected.value?.id === row.id) selected.value = result;
    notice.value = action === "ban" ? t("subscriptionIpLimit.banRecorded") : t("subscriptionIpLimit.unbanRecorded");
    if (action === "ban") banReason.value = "";
    await load();
  } catch (cause) { if (id === props.subscriptionId) error.value = cause instanceof Error ? cause.message : t("subscriptionIpLimit.operationFailed"); }
  finally { if (id === props.subscriptionId) busy.value = false; }
}
watch(() => props.subscriptionId, () => { ++readVersion; detail.value = null; rows.value = []; selected.value = null; page.value = 1; busy.value = false; notice.value = ""; banReason.value = ""; void load(true); }, { immediate: true });
watch([state, search], () => { page.value = 1; void load(); });
</script>
<template>
  <section class="form-grid" :aria-label="t('subscriptionIpLimit.region')">
    <h2>{{ t('subscriptionIpLimit.title') }}</h2>
    <p class="subtitle">{{ t('subscriptionIpLimit.description') }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
    <div v-if="detail" class="form-grid">
      <p class="message">{{ t('subscriptionIpLimit.currentAllowance', { allowance: admissionAllowance }) }}</p>
      <p class="subtitle">{{ admissionSource }}</p>
      <IpPolicyTransition v-if="detail.effective_ip_policy?.transition" :transition="detail.effective_ip_policy.transition" />
      <form v-if="auth.can('subscriptions', 'update')" class="form-grid" @submit.prevent="save"><p class="subtitle">{{ t('subscriptionIpLimit.overrideDescription') }}</p>
        <p v-if="detail.effective_ip_policy?.transition" class="subtitle">{{ t('subscriptionIpLimit.pendingEdit') }}</p>
        <label class="field"><span><input v-model="choice.enabled" type="checkbox" :disabled="busy" /> {{ t('subscriptionIpLimit.limitEnabled') }}</span></label>
        <NumField v-model="choice.max_ips" :label="t('subscriptionIpLimit.maxIps')" />
        <NumField v-model="choice.lease_seconds" :label="t('subscriptionIpLimit.activityWindow')" />
        <NumField v-model="choice.ban_seconds" :label="t('subscriptionIpLimit.autoBanDuration')" />
        <label class="field"><span>{{ t('subscriptionIpLimit.behavior') }}</span><select v-model="choice.mode" :aria-label="t('subscriptionIpLimit.behavior')"><option value="reject_new">{{ t('subscriptionIpLimit.rejectNew') }}</option><option value="replace_oldest">{{ t('subscriptionIpLimit.replaceOldest') }}</option></select></label>
        <template v-if="detail.transition_options"><label class="field"><span>{{ t('subscriptionIpLimit.tightening') }}</span><select v-model="transitionMode" :aria-label="t('subscriptionIpLimit.tightening')"><option v-for="option in detail.transition_options.choices" :key="option.mode" :value="option.mode" :disabled="!option.available">{{transitionLabels[option.mode]}}{{option.available?'':' — ' + t('subscriptionIpLimit.unavailable')}}</option></select></label><p class="subtitle">{{ t('subscriptionIpLimit.configuredDefault', { mode: transitionLabels[detail.transition_options.default_mode] }) }}</p><p v-if="!transitionAvailable" class="message">{{ t('subscriptionIpLimit.transitionUnavailable') }}</p></template>
        <button class="btn" :disabled="busy || loading || !transitionAvailable || !Number.isSafeInteger(Number(choice.max_ips)) || Number(choice.max_ips)<=0 || Number(choice.max_ips)>detail.defaults.max_ips_ceiling || !Number.isSafeInteger(Number(choice.lease_seconds)) || Number(choice.lease_seconds)<=0 || Number(choice.lease_seconds)>detail.defaults.max_lease_seconds || !Number.isSafeInteger(Number(choice.ban_seconds)) || Number(choice.ban_seconds)<=0 || Number(choice.ban_seconds)>detail.defaults.max_ban_seconds">{{ t('subscriptionIpLimit.save') }}</button>
      </form>
      <div v-else-if="admissionPolicy" class="detail-line"><span>{{ t('subscriptionIpLimit.allowanceWindow') }}</span><strong>{{ allowance(admissionPolicy) }} / {{ faNumber(admissionPolicy.lease_seconds) }} {{ t('subscriptionIpLimit.seconds') }}</strong></div>
    </div>
    <div class="toolbar"><label class="field"><span>{{ t('subscriptionIpLimit.search') }}</span><input v-model="search" type="search" dir="ltr" :aria-label="t('subscriptionIpLimit.search')" /></label><label class="field"><span>{{ t('subscriptionIpLimit.status') }}</span><select v-model="state" :aria-label="t('subscriptionIpLimit.status')"><option value="">{{ t('subscriptionIpLimit.all') }}</option><option value="active">{{ t('subscriptionIpLimit.active') }}</option><option value="blocked">{{ t('subscriptionIpLimit.blocked') }}</option><option value="inactive">{{ t('subscriptionIpLimit.inactive') }}</option></select></label><button class="btn secondary" :disabled="loading" @click="load(true)">{{ t('subscriptionIpLimit.refresh') }}</button></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t('subscriptionIpLimit.ip') }}</th><th>{{ t('subscriptionIpLimit.lastNode') }}</th><th>{{ t('subscriptionIpLimit.activityExpires') }}</th><th>{{ t('subscriptionIpLimit.banExpires') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{ 'selected-row': selected?.id === row.id }" tabindex="0" @click="selected = row" @keydown.enter="selected = row"><td dir="ltr">{{ row.source_ip }}</td><td>{{ faNumber(row.last_node_id) }}</td><td>{{ faDate(row.expires_at) }}</td><td>{{ row.blocked_until ? faDate(row.blocked_until) : '—' }}</td></tr></tbody></table></div>
    <p v-if="loading" class="empty">{{ t('subscriptionIpLimit.loading') }}</p><p v-else-if="!error && !rows.length" class="empty">{{ t('subscriptionIpLimit.empty') }}</p>
    <div class="pager"><button :disabled="page <= 1 || loading" :aria-label="t('subscriptionIpLimit.previousPage')" @click="page--; load()">‹</button><span>{{ t('subscriptionIpLimit.pageCount', { page: faNumber(page), total: faNumber(total) }) }}</span><button :disabled="page >= pages || loading" :aria-label="t('subscriptionIpLimit.nextPage')" @click="page++; load()">›</button></div>
    <div v-if="selected" class="form-grid"><h3 dir="ltr">{{ selected.source_ip }}</h3><p v-if="selected.block_reason" class="message">{{ reasons[selected.block_reason] ?? selected.block_reason }}</p><template v-if="auth.can('subscriptions', 'update')"><NumField v-model="banSeconds" :label="t('subscriptionIpLimit.banDuration')" /><label class="field"><span>{{ t('subscriptionIpLimit.banReason') }}</span><textarea v-model="banReason" minlength="3" maxlength="250" /></label><div class="toolbar"><button class="btn danger" :disabled="busy || Number(banSeconds) <= 0 || banReason.trim().length < 3" @click="restrict('ban')">{{ t('subscriptionIpLimit.banSelected') }}</button><button class="btn secondary" :disabled="busy" @click="restrict('unban')">{{ t('subscriptionIpLimit.unbanSelected') }}</button></div></template></div>
  </section>
</template>
