<script setup lang="ts">
import type { IpPolicyTransitionRead } from "@papilio/api";
import { faDate } from "@papilio/ui";
import { ipAllowanceText } from "./policy";

defineProps<{ transition: IpPolicyTransitionRead }>();
const reasons: Record<IpPolicyTransitionRead["reason"], string> = {
  ip_policy_draining: "Existing recorded leases must drain before the requested allowance takes effect.",
  legacy_lease_history_unknown: "Earlier connections have no complete lease history. The requested allowance cannot safely take effect yet.",
  closed_receipts_unavailable: "Verified connection-closure receipts are unavailable. The requested allowance remains blocked.",
};
</script>

<template>
  <section class="hint-box form-grid" aria-label="Pending source IP policy" aria-live="polite">
    <div class="detail-line"><span>Requested allowance</span><strong>{{ ipAllowanceText(transition.target_policy) }}</strong></div>
    <div class="detail-line"><span>Transition status</span><strong>{{ transition.status === 'draining' ? 'Waiting for existing leases' : 'Blocked' }}</strong></div>
    <p class="subtitle">{{ reasons[transition.reason] }}</p>
    <div v-if="transition.retry_at" class="detail-line"><span>Earliest retry</span><strong>{{ faDate(transition.retry_at) }}</strong></div>
    <p v-if="transition.mode === 'drain_leases'" class="subtitle">Refresh to check the recorded transition. This does not confirm immediate disconnection of existing devices.</p>
    <p v-else class="subtitle">Activation requires verified closure receipts; it is unavailable from this panel.</p>
    <p class="subtitle">The requested allowance is not active. The current recorded allowance and purchased terms remain unchanged.</p>
    <p class="message">Admissions and lease renewals are paused while this transition is pending.</p>
  </section>
</template>
