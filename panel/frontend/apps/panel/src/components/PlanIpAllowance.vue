<script setup lang="ts">
import type { IpLimitChoice, PlanIpPolicyRead } from "@papilio/api";
import { ipAllowanceText } from "./ipLimits/policy";

defineProps<{ policy?: PlanIpPolicyRead | null; configured?: IpLimitChoice | null }>();
</script>

<template>
  <section class="hint-box form-grid" aria-label="Plan source IP allowance">
    <div class="detail-line"><span>Concurrent source IP allowance</span><strong>{{ policy ? ipAllowanceText(policy.policy) : configured ? ipAllowanceText(configured) : 'Allowance unavailable from this API' }}</strong></div>
    <p v-if="policy" class="subtitle">{{policy.source==='plan_override'?'Explicit plan terms':'Current purchase-time defaults'}}. The allowance is captured with the purchase and shared by that subscription's configurations.</p>
    <p v-else class="subtitle">The API has not supplied the effective purchase allowance. Refresh the offer before relying on these terms.</p>
    <p class="subtitle">API admission decisions only. Core enforcement is not verified. Source IP counts do not represent device counts.</p>
  </section>
</template>
