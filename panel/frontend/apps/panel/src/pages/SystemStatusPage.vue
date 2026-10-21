<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { request } from "@papilio/api";
import type { DiagnosticOperation, SystemStatus, ManagedSchedule } from "@papilio/api";
import { useAuth } from "@papilio/auth";

const { t } = useI18n();
const auth = useAuth();
const schedules = ref<ManagedSchedule[]>([]);
const status = ref<SystemStatus | null>(null);
const operation = ref<DiagnosticOperation | null>(null);
const busy = ref(false);
const error = ref("");
const lifetime = new AbortController();
onBeforeUnmount(() => lifetime.abort());

async function refresh(): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    status.value = await request<SystemStatus>("/v1/system/status", "GET", undefined, { signal: lifetime.signal });
    if (auth.can("system", "write")) {
      schedules.value = await request<ManagedSchedule[]>("/v1/system/schedules", "GET", undefined, { signal: lifetime.signal });
    }
    if (operation.value) {
      operation.value = await request<DiagnosticOperation>(`/v1/system/operations/${operation.value.id}`, "GET", undefined, { signal: lifetime.signal });
    }
  } catch (cause) {
    if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("login.failed");
  } finally {
    busy.value = false;
  }
}

async function saveSchedule(schedule: ManagedSchedule): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    const updated = await request<ManagedSchedule>(`/v1/system/schedules/${schedule.key}`, "PUT", {
      enabled: schedule.enabled, interval_seconds: schedule.interval_seconds, expected_changed_at: schedule.changed_at,
    }, { signal: lifetime.signal });
    schedules.value = schedules.value.map(row => row.key === updated.key ? updated : row);
  } catch (cause) {
    if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("login.failed");
  } finally {
    busy.value = false;
  }
}

async function probe(kind: "io" | "cpu"): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    operation.value = await request<DiagnosticOperation>("/v1/system/probes", "POST", { kind, request_key: crypto.randomUUID() }, { signal: lifetime.signal });
  } catch (cause) {
    if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("login.failed");
  } finally {
    busy.value = false;
  }
}

async function cancel(): Promise<void> {
  if (!operation.value) return;
  busy.value = true;
  error.value = "";
  try {
    operation.value = await request<DiagnosticOperation>(`/v1/system/operations/${operation.value.id}/cancel`, "POST", undefined, { signal: lifetime.signal });
  } catch (cause) {
    if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("login.failed");
  } finally {
    busy.value = false;
  }
}
onMounted(refresh);
</script>
<template>
  <section class="form-grid">
    <header class="page-heading"><h1>{{ t("foundation.statusTitle") }}</h1><p>{{ t("foundation.releaseHelp") }}</p></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <button class="btn secondary" :disabled="busy" @click="refresh">{{ t("foundation.refresh") }}</button>
    <dl v-if="status" class="form-grid" data-testid="system-status">
      <div><dt>{{ t("foundation.version") }}</dt><dd>{{ status.version }}</dd></div>
      <div><dt>{{ t("foundation.environment") }}</dt><dd>{{ status.environment }}</dd></div>
      <div><dt>{{ t("foundation.instance") }}</dt><dd>{{ status.instance }}</dd></div>
      <div v-for="[key, ready] in [['database', status.database], ['cache', status.cache], ['workers', status.workers_ready]]" :key="String(key)"><dt>{{ t(`foundation.${key}`) }}</dt><dd>{{ t(ready ? 'foundation.ready' : 'foundation.unavailable') }}</dd></div>
    </dl>
    <section v-if="status?.workers.length" class="form-grid">
      <div v-for="worker in status.workers" :key="worker.role"><strong>{{ worker.role }}</strong><p>{{ worker.queue }}</p><p>{{ t('foundation.observed') }}: {{ new Date(worker.observed_at).toLocaleString() }}</p></div>
    </section>
    <section class="form-grid">
      <h2>{{ t("foundation.diagnostics") }}</h2><p>{{ t("foundation.diagnosticsHelp") }}</p>
      <button class="btn" data-testid="probe-io" :disabled="busy" @click="probe('io')">{{ t("foundation.ioCheck") }}</button>
      <button class="btn secondary" data-testid="probe-cpu" :disabled="busy" @click="probe('cpu')">{{ t("foundation.cpuCheck") }}</button>
      <div v-if="operation" data-testid="probe-operation" aria-live="polite">
        <p>{{ t('foundation.operation') }}: {{ operation.id }}</p>
        <p>{{ t(`foundation.states.${operation.status}`) }} · {{ t('foundation.attempts') }}: {{ operation.attempts }}</p>
        <p v-if="operation.error_code" role="alert">{{ operation.error_code }}</p>
        <p v-if="operation.result">{{ t('foundation.worker') }}: {{ operation.result.worker_host }} / {{ operation.result.worker_pid }}</p>
        <button v-if="operation.status === 'queued'" class="btn secondary" :disabled="busy" @click="cancel">{{ t('foundation.cancel') }}</button>
      </div>
    </section>
    <section v-if="schedules.length" class="form-grid">
      <h2>{{ t('foundation.schedules') }}</h2><p>{{ t('foundation.scheduleHelp') }}</p>
      <form v-for="schedule in schedules" :key="schedule.key" class="form-grid" :data-testid="`schedule-${schedule.key}`" @submit.prevent="saveSchedule(schedule)">
        <h3>{{ t(`foundation.scheduleNames.${schedule.key}`) }}</h3>
        <label class="field"><span>{{ t('foundation.interval') }}</span><input v-model.number="schedule.interval_seconds" type="number" min="1" max="2147483647" required :disabled="busy" /></label>
        <label><input v-model="schedule.enabled" type="checkbox" :disabled="busy" /> {{ t('foundation.enabled') }}</label>
        <button class="btn secondary" type="submit" :disabled="busy">{{ t('foundation.save') }}</button>
      </form>
    </section>
  </section>
</template>
