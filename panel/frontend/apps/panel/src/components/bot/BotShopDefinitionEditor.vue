<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import type { BotShopDefinition, ShopLocale } from "@papilio/api";

const draft = defineModel<BotShopDefinition>({ required: true });
defineProps<{ disabled: boolean }>();
const { t } = useI18n();
const textLocale = ref<ShopLocale>("en");
const numericFields = ["page_size", "retry_seconds", "lease_seconds", "max_attempts", "confirmation_ttl_seconds"] as const;
const locales: { key: ShopLocale; label: string }[] = [
  { key: "en", label: "English" },
  { key: "fa", label: "فارسی" },
  { key: "ru", label: "Русский" },
  { key: "zh", label: "中文" },
];
</script>

<template>
  <fieldset class="form-grid" :disabled="disabled">
    <label class="field"><span>{{ t('botShop.fields.public_origin') }}</span><input v-model="draft.public_origin" data-testid="shop-public_origin" type="url" maxlength="500" dir="ltr" required /></label>
    <p class="hint-box">{{ t('botShop.originHelp') }}</p>
    <label><input v-model="draft.enabled" data-testid="shop-enabled" type="checkbox" /> {{ t('botShop.fields.enabled') }}</label>
    <label><input v-model="draft.delivery_enabled" data-testid="shop-delivery_enabled" type="checkbox" /> {{ t('botShop.fields.delivery_enabled') }}</label>
    <p>{{ t('botShop.pauseHelp') }}</p>
    <label class="field"><span>{{ t('botShop.fields.locale') }}</span><select v-model="draft.locale" data-testid="shop-locale"><option v-for="locale in locales" :key="locale.key" :value="locale.key">{{ locale.label }}</option></select></label>
    <details><summary data-testid="shop-advanced">{{ t('botShop.advanced') }}</summary><div class="form-grid">
      <label v-for="field in numericFields" :key="field" class="field"><span>{{ t(`botShop.fields.${field}`) }}</span><input v-model.number="draft[field]" :data-testid="`shop-${field}`" type="number" min="1" max="2147483647" step="1" required /></label>
      <label class="field"><span>{{ t('botShop.fields.ambiguous_delivery') }}</span><select v-model="draft.ambiguous_delivery" data-testid="shop-ambiguous_delivery"><option value="hold">{{ t('botShop.hold') }}</option><option value="retry">{{ t('botShop.retry') }}</option></select></label>
      <p class="hint-box">{{ t('botShop.retryHelp') }}</p>
    </div></details>
    <details><summary data-testid="shop-texts">{{ t('botShop.texts') }}</summary><div class="form-grid">
      <p>{{ t('botShop.templateHelp') }}</p>
      <p class="hint-box" dir="ltr">$name · $product · $amount · $balance · $page · $invoice_id · $order_id · $destination · $instructions · $reference · $status · $url · $reason</p>
      <label class="field"><span>{{ t('botShop.textLocale') }}</span><select v-model="textLocale" data-testid="shop-text-locale"><option v-for="locale in locales" :key="locale.key" :value="locale.key">{{ locale.label }}</option></select></label>
      <label v-for="(_, key) in draft.texts[textLocale]" :key="`${textLocale}:${key}`" class="field"><span>{{ t(`botShop.messages.${key}`) }}</span><textarea v-model="draft.texts[textLocale][key]" :data-testid="`shop-text-${key}`" :dir="textLocale === 'fa' ? 'rtl' : 'ltr'" maxlength="4096" required /></label>
    </div></details>
  </fieldset>
</template>
