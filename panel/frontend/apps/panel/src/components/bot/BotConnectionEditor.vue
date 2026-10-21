<script setup lang="ts">
import { useI18n } from "vue-i18n";
import type { BotDraft } from "@papilio/api";
const draft = defineModel<BotDraft>({ required: true });
const props = defineProps<{ disabled: boolean; tokenRequired: boolean; testPrefix: string }>();
const { t } = useI18n();
const numericFields = ["poll_timeout_seconds", "http_timeout_seconds", "update_limit", "max_response_bytes", "pairing_ttl_seconds", "failure_retry_seconds"] as const;
</script>

<template>
  <fieldset class="form-grid" :disabled="props.disabled">
    <label class="field"><span>{{ t('bots.label') }}</span><input v-model="draft.label" :data-testid="`${testPrefix}-label`" required maxlength="80" /></label>
    <label class="field"><span>{{ t(tokenRequired ? 'bots.token' : 'bots.replaceToken') }}</span><input v-model="draft.token" :data-testid="`${testPrefix}-token`" type="password" autocomplete="new-password" :required="tokenRequired" minlength="20" maxlength="512" dir="ltr" /></label>
    <p class="hint-box">{{ t('bots.tokenHelp') }}</p>
    <label><input v-model="draft.schedule.enabled" :data-testid="`${testPrefix}-enabled`" type="checkbox" /> {{ t('bots.enabled') }}</label>
    <label class="field"><span>{{ t('bots.interval') }}</span><input v-model.number="draft.schedule.interval_seconds" :data-testid="`${testPrefix}-interval`" type="number" min="1" max="2147483647" step="1" required /></label>
    <details><summary :data-testid="`${testPrefix}-advanced`">{{ t('bots.advanced') }}</summary><div class="form-grid">
      <p>{{ t('bots.runtimeHelp') }}</p>
      <label class="field"><span>{{ t('bots.fields.api_base_url') }}</span><input v-model="draft.runtime.api_base_url" :data-testid="`${testPrefix}-api_base_url`" type="url" required maxlength="500" dir="ltr" /></label>
      <label v-for="field in numericFields" :key="field" class="field"><span>{{ t(`bots.fields.${field}`) }}</span><input v-model.number="draft.runtime[field]" :data-testid="`${testPrefix}-${field}`" type="number" min="1" :max="field === 'update_limit' ? 100 : 2147483647" step="1" required /></label>
    </div></details>
  </fieldset>
</template>
