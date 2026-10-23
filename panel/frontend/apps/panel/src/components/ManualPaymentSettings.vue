<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, request, type ManualPaymentDefinition, type ManualPaymentSettings } from "@papilio/api";

const { t } = useI18n();
const settings = ref<ManualPaymentSettings | null>(null);
const definition = ref<ManualPaymentDefinition | null>(null);
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
onBeforeUnmount(() => lifetime.abort());
async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); }
  catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("serviceSetup.failed"); }
  finally { busy.value = false; }
}
async function refresh(): Promise<void> {
  await perform(async () => {
    try {
      settings.value = await request<ManualPaymentSettings>("/v1/payment-settings", "GET", undefined, { signal: lifetime.signal });
      definition.value = { ...settings.value.definition };
    } catch (cause) {
      if (!(cause instanceof ApiError) || cause.status !== 404) throw cause;
      settings.value = null;
      definition.value = await request<ManualPaymentDefinition>("/v1/payment-defaults", "GET", undefined, { signal: lifetime.signal });
    }
  });
}
async function save(): Promise<void> {
  if (!definition.value) return;
  const body = { ...definition.value };
  const current = settings.value;
  await perform(async () => {
    settings.value = current
      ? await request<ManualPaymentSettings>("/v1/payment-settings", "PUT", { ...body, expected_revision: current.revision }, { signal: lifetime.signal })
      : await request<ManualPaymentSettings>("/v1/payment-settings", "POST", body, { signal: lifetime.signal });
    definition.value = { ...settings.value.definition };
  });
}
onMounted(refresh);
</script>

<template>
  <section class="card card-pad form-grid">
    <h2>{{ t('invoices.settingsTitle') }}</h2><p>{{ t('invoices.settingsHelp') }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <button class="btn secondary" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
    <p v-if="settings">{{ t('productCatalog.revision') }} <span data-testid="payment-revision">{{ settings.revision }}</span></p>
    <form v-if="definition" @submit.prevent="save"><fieldset class="form-grid" :disabled="busy">
      <label class="field"><span>{{ t('invoices.recipient') }}</span><input v-model="definition.recipient" data-testid="payment-recipient" required maxlength="80" /></label>
      <label class="field"><span>{{ t('invoices.destination') }}</span><input v-model="definition.destination" data-testid="payment-destination" required maxlength="120" dir="ltr" /></label>
      <label class="field"><span>{{ t('invoices.instructions') }}</span><textarea v-model="definition.instructions" data-testid="payment-instructions" maxlength="2000" /></label>
      <label class="field"><span>{{ t('invoices.fileLimit') }}</span><input v-model.number="definition.receipt_max_bytes" data-testid="payment-max-bytes" type="number" min="1" max="1073741823" step="1" required /></label>
      <label><input v-model="definition.enabled" data-testid="payment-enabled" type="checkbox" /> {{ t('invoices.enabled') }}</label>
      <button class="btn" type="submit" data-testid="payment-save">{{ t('invoices.saveSettings') }}</button>
    </fieldset></form>
  </section>
</template>
