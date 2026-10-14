<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { item, type CustomerLoyalty } from "@papilio/api";
import { useI18n } from "vue-i18n";
import { useLocalizedFormats } from "../composables/useLocalizedFormats";
const props = defineProps<{ customerId: number }>();
const { t } = useI18n();
const { number } = useLocalizedFormats();
const result = ref<CustomerLoyalty | null>(null), loading = ref(false), error = ref("");
let sequence = 0;
async function refresh(): Promise<void> {
  const current = ++sequence; loading.value = true; error.value = "";
  try {
    const value = await item<CustomerLoyalty>("/v1/customer/loyalty");
    if (current !== sequence) return;
    if (value.customer_id !== props.customerId) throw new Error(t("customerLoyalty.wrongAccount"));
    result.value = value;
  } catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : t("customerLoyalty.loadFailed"); }
  finally { if (current === sequence) loading.value = false; }
}
onMounted(() => void refresh());
onUnmounted(() => { ++sequence; });
</script>
<template>
  <section class="card card-pad form-grid" :aria-label="t('customerLoyalty.region')">
    <div class="page-head"><div><p class="eyebrow">{{ t("customerLoyalty.eyebrow") }}</p><h2>{{ t("customerLoyalty.title") }}</h2></div><button type="button" class="btn small secondary" :disabled="loading" @click="refresh">{{ t("customerLoyalty.refresh") }}</button></div>
    <p v-if="loading">{{ t("customerLoyalty.loading") }}</p>
    <p v-if="error" class="message error" role="alert">{{error}}</p>
    <template v-if="result && !loading && !error">
      <h3>{{result.tier?.title ?? t('customerLoyalty.noTier')}}</h3>
      <p>{{ t("customerLoyalty.qualifyingCredit") }}: <strong>{{number(result.purchased_bytes / 1024 ** 3)}} GiB</strong> · {{number(result.purchase_count)}} {{ t("customerLoyalty.qualifyingPurchases") }}.</p>
      <template v-if="result.next_tier">
        <p>{{ t("customerLoyalty.nextTier") }}: <strong>{{result.next_tier.title}}</strong> · {{ t("customerLoyalty.threshold") }} {{number(result.next_tier.minimum_bytes / 1024 ** 3)}} GiB.</p>
        <progress :value="result.purchased_bytes" :max="result.next_tier.minimum_bytes" :aria-label="t('customerLoyalty.progressLabel', { tier: result.next_tier.title })" />
        <p>{{number(Math.max(result.next_tier.minimum_bytes - result.purchased_bytes, 0) / 1024 ** 3)}} GiB {{ t("customerLoyalty.remainingToNext") }}.</p>
      </template>
      <p v-else-if="result.tier">{{ t("customerLoyalty.highestTier") }}</p>
      <p class="subtitle">{{ t("customerLoyalty.discountNote") }}</p>
    </template>
  </section>
</template>
<style scoped>
progress { width: 100%; accent-color: var(--accent); }
</style>
