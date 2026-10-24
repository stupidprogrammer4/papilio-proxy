<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, request, type ManagedServiceSynchronization } from "@papilio/api";

const props = defineProps<{ serviceId: string }>();
const { t } = useI18n();
const record = ref<ManagedServiceSynchronization | null>(null);
const enabled = ref(false); const interval = ref<number | "">("");
const busy = ref(false); const error = ref("");
const lifetime = new AbortController();
onBeforeUnmount(() => lifetime.abort());
const endpoint = `/v1/services/${props.serviceId}/synchronization`;

function accept(value: ManagedServiceSynchronization): void {
  record.value = value; enabled.value = value.enabled; interval.value = value.interval_seconds;
}
async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); }
  catch (cause) {
    if (!lifetime.signal.aborted) error.value = cause instanceof ApiError && cause.status === 409 ? t("serviceSync.conflict") : cause instanceof Error ? cause.message : t("serviceSetup.failed");
  } finally { busy.value = false; }
}
async function refresh(): Promise<void> {
  await perform(async () => { accept(await request<ManagedServiceSynchronization>(endpoint, "GET", undefined, { signal: lifetime.signal })); });
}
async function save(): Promise<void> {
  const current = record.value;
  if (!current) return;
  await perform(async () => {
    accept(await request<ManagedServiceSynchronization>(endpoint, "PUT", {
      enabled: enabled.value, interval_seconds: interval.value, expected_revision: current.revision,
    }, { signal: lifetime.signal }));
  });
}
onMounted(refresh);
</script>

<template>
  <section class="card card-pad form-grid" data-testid="service-synchronization">
    <h2 data-testid="service-sync-title">{{ t('serviceSync.title') }}</h2>
    <p>{{ t('serviceSync.help') }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <button class="btn secondary" data-testid="service-sync-refresh" :disabled="busy" @click="refresh">{{ t('foundation.refresh') }}</button>
    <form v-if="record" @submit.prevent="save"><fieldset class="form-grid" :disabled="busy">
      <label class="check-field"><input v-model="enabled" type="checkbox" data-testid="service-sync-enabled" />{{ t('foundation.enabled') }}</label>
      <label class="field"><span>{{ t('foundation.interval') }}</span><input v-model.number="interval" data-testid="service-sync-interval" type="number" min="1" max="2147483647" step="1" required /></label>
      <button class="btn" data-testid="service-sync-save" type="submit">{{ t('foundation.save') }}</button>
    </fieldset></form>
    <template v-if="record">
      <p>{{ t('serviceSync.status') }}: {{ record.enabled ? t(`foundation.states.${record.status}`) : t('serviceSync.paused') }}</p>
      <p>{{ t('foundation.attempts') }}: {{ record.attempts }}</p>
      <p v-if="record.last_completed_at">{{ t('serviceSync.lastCheck') }}: {{ new Date(record.last_completed_at).toLocaleString() }}</p>
      <p v-if="record.enabled">{{ t('serviceSync.nextCheck') }}: {{ new Date(record.due_at).toLocaleString() }}</p>
      <p v-if="record.error_code">{{ t('serviceSync.lastError') }}: <code>{{ record.error_code }}</code></p>
    </template>
    <p class="hint-box">{{ t('serviceSync.pauseHelp') }} <RouterLink to="/">{{ t('foundation.schedules') }}</RouterLink></p>
  </section>
</template>
