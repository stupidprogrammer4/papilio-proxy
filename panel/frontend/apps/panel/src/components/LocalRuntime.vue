<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, request, type LocalDeliveryPolicy, type LocalNodeRead, type LocalNodeOperation } from "@papilio/api";

const { t } = useI18n();
const record = ref<LocalNodeRead | null>(null);
const draft = ref<LocalDeliveryPolicy | null>(null);
const busy = ref(false), error = ref("");
const lifetime = new AbortController();
let retryKey = newRequestKey();
onBeforeUnmount(() => lifetime.abort());
const endpoint = "/v1/system/local-node";
function accept(value: LocalNodeRead): void {
  record.value = value;
  draft.value = { enabled: value.delivery.enabled, retry_interval_seconds: value.delivery.retry_interval_seconds, max_attempts: value.delivery.max_attempts };
}
async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); }
  catch (cause) {
    if (!lifetime.signal.aborted) error.value = cause instanceof ApiError && cause.status === 409 ? t("localNode.conflict") : cause instanceof Error ? cause.message : t("nodes.failed");
  } finally { busy.value = false; }
}
async function refresh(): Promise<void> {
  await perform(async () => {
    try { accept(await request<LocalNodeRead>(endpoint, "GET", undefined, { signal: lifetime.signal })); }
    catch (cause) { if (!(cause instanceof ApiError && cause.status === 404)) throw cause; }
  });
}
async function save(): Promise<void> {
  const current = record.value, selected = draft.value;
  if (!current || !selected) return;
  await perform(async () => {
    const delivery = await request<LocalNodeRead["delivery"]>(endpoint + "/delivery", "PUT", { ...selected, expected_revision: current.delivery.revision }, { signal: lifetime.signal });
    accept({ ...current, delivery });
  });
}
async function retry(): Promise<void> {
  if (!record.value) return;
  await perform(async () => {
    const operation = await request<LocalNodeOperation>(endpoint + "/operations", "POST", { request_key: retryKey }, { signal: lifetime.signal });
    retryKey = newRequestKey();
    if (record.value) record.value = { ...record.value, operation };
  });
}
onMounted(refresh);
</script>
<template>
  <section v-if="record || error" class="card card-pad form-grid" data-testid="local-runtime">
    <h2>{{ t('localNode.title') }}</h2>
    <p>{{ t('localNode.statusHelp') }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <button class="btn secondary" data-testid="local-runtime-refresh" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
    <template v-if="record">
      <p>{{ record.definition.node.name }} · {{ record.definition.core_name }}</p>
      <p dir="ltr">{{ record.definition.public_host }}:{{ record.definition.public_port }}</p>
      <p data-testid="local-runtime-state">{{ t(`foundation.states.${record.operation.status}`) }} · {{ t('foundation.attempts') }}: {{ record.operation.attempts }}</p>
      <p v-if="record.operation.error_code"><code>{{ record.operation.error_code }}</code></p>
      <form v-if="draft" @submit.prevent="save"><fieldset class="form-grid" :disabled="busy">
        <label class="check-field"><input v-model="draft.enabled" data-testid="local-delivery-enabled" type="checkbox" />{{ t('localNode.deliveryEnabled') }}</label>
        <label class="field"><span>{{ t('localNode.retryInterval') }}</span><input v-model.number="draft.retry_interval_seconds" data-testid="local-retry-interval" type="number" min="1" max="2147483647" step="1" required /></label>
        <label class="field"><span>{{ t('localNode.maxAttempts') }}</span><input v-model.number="draft.max_attempts" data-testid="local-max-attempts" type="number" min="1" max="2147483647" step="1" required /></label>
        <button class="btn" data-testid="local-delivery-save" type="submit">{{ t('foundation.save') }}</button>
      </fieldset></form>
      <button class="btn secondary" data-testid="local-runtime-retry" :disabled="busy" @click="retry">{{ t('localNode.retry') }}</button>
      <p class="hint-box">{{ t('localNode.pauseHelp') }}</p>
    </template>
  </section>
</template>
