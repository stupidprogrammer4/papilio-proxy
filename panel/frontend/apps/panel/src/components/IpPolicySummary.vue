<script setup lang="ts">
import type { EffectiveIpPolicyRead, PurchasedIpPolicyRead } from "@papilio/api";
import { faDate } from "@papilio/ui";
import { ipAllowanceText } from "./ipLimits/policy";
import IpPolicyTransition from "./ipLimits/IpPolicyTransition.vue";

defineProps<{ purchased?: PurchasedIpPolicyRead | null; effective?: EffectiveIpPolicyRead; compact?: boolean }>();
const sources = { subscription_override: "Recorded operational policy", purchased_snapshot: "Purchased allowance", legacy_unrestricted: "Legacy: no recorded restriction" };
</script>

<template>
  <section aria-label="Subscription source IP allowance" :class="compact ? 'form-grid' : 'hint-box form-grid'">
    <div class="detail-line"><span>Purchased concurrency</span><strong>{{ purchased ? ipAllowanceText(purchased.policy) : purchased === null ? 'Legacy: no purchased snapshot' : 'Snapshot unavailable from this API' }}</strong></div>
    <template v-if="purchased && !compact"><p class="subtitle">Captured {{faDate(purchased.captured_at)}} · {{purchased.source==='plan_override'?'Explicit plan policy':'Purchase-time defaults'}}<span v-if="purchased.plan_id!==null"> · Plan #{{purchased.plan_id}}</span></p></template>
    <div v-if="effective" class="detail-line"><span>Current admission allowance</span><strong>{{ipAllowanceText(effective.policy)}}</strong></div>
    <p v-if="effective" class="subtitle">{{sources[effective.source]}} · Shared by this subscription's configurations, not by independent subscriptions.</p>
    <p v-if="effective?.source==='subscription_override'" class="subtitle">This operational override does not rewrite the purchased snapshot.</p>
    <IpPolicyTransition v-if="effective?.transition" :transition="effective.transition" />
    <p class="message">API admission decisions only. Core enforcement is not verified. Source IP counts do not represent device counts.</p>
  </section>
</template>
