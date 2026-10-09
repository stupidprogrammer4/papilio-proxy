<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { item, type CustomerLoyalty } from "@papilio/api";
import { faNumber } from "@papilio/ui";
const props = defineProps<{ customerId: number }>();
const result = ref<CustomerLoyalty | null>(null), loading = ref(false), error = ref("");
let sequence = 0;
async function refresh(): Promise<void> {
  const current = ++sequence; loading.value = true; error.value = "";
  try {
    const value = await item<CustomerLoyalty>("/v1/customer/loyalty");
    if (current !== sequence) return;
    if (value.customer_id !== props.customerId) throw new Error("The purchase progress does not belong to this account.");
    result.value = value;
  } catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : "Could not load purchase progress."; }
  finally { if (current === sequence) loading.value = false; }
}
onMounted(() => void refresh());
onUnmounted(() => { ++sequence; });
</script>
<template>
  <section class="card card-pad form-grid" aria-label="Customer loyalty">
    <div class="page-head"><div><p class="eyebrow">PURCHASE REWARDS</p><h2>My tier and purchase progress</h2></div><button type="button" class="btn small secondary" :disabled="loading" @click="refresh">Refresh purchase progress</button></div>
    <p v-if="loading">Loading purchase progress…</p>
    <p v-if="error" class="message error" role="alert">{{error}}</p>
    <template v-if="result && !loading && !error">
      <h3>{{result.tier?.title ?? 'No assigned tier'}}</h3>
      <p>Qualifying purchase credit: <strong>{{faNumber(result.purchased_bytes / 1024 ** 3)}} GiB</strong> · {{faNumber(result.purchase_count)}} qualifying purchases.</p>
      <template v-if="result.next_tier">
        <p>Next tier: <strong>{{result.next_tier.title}}</strong> · threshold {{faNumber(result.next_tier.minimum_bytes / 1024 ** 3)}} GiB.</p>
        <progress :value="result.purchased_bytes" :max="result.next_tier.minimum_bytes" :aria-label="`Purchase credit toward ${result.next_tier.title}`" />
        <p>{{faNumber(Math.max(result.next_tier.minimum_bytes - result.purchased_bytes, 0) / 1024 ** 3)}} GiB of qualifying purchase credit to the next tier.</p>
      </template>
      <p v-else-if="result.tier">You have reached the highest configured tier.</p>
      <p class="subtitle">Your final discount is calculated for the selected plan. Purchase credit and service usage are separate values.</p>
    </template>
  </section>
</template>
<style scoped>
progress { width: 100%; accent-color: var(--accent); }
</style>
