<script setup lang="ts">
import { onMounted, ref } from "vue";
import { item, query, request, type Host, type ConfigurationDraft, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faNumber } from "@papilio/ui";
import NumField from "@papilio/ui/NumField.vue";
import { useI18n } from "vue-i18n";
import { useLocalizedFormats } from "../composables/useLocalizedFormats";
const props = defineProps<{ configuration: ConfigurationDraft }>(); const auth = useAuth();
const { t } = useI18n(); const { number } = useLocalizedFormats();
const rows = ref<Host[]>([]); const page = ref(1); const pages = ref(1); const q = ref(""); const state = ref<"loading" | "ready" | "error">("loading"); const error = ref(""); const busy = ref(false);
const selected = ref<Host | null>(null); const label = ref(""); const address = ref(""); const port = ref(String(props.configuration.listen_port)); const enabled = ref(false);
async function load(): Promise<void> {
  state.value = "loading"; error.value = ""; const requested = page.value;
  try { const result = await request<Page<Host>>(`/v1/admin/network/hosts?${query({ configuration_id: props.configuration.id, page: requested, q: q.value })}`); if (requested !== page.value) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; state.value = "ready"; }
  catch (cause) { state.value = "error"; error.value = cause instanceof Error ? cause.message : t("configurationHosts.operationFailed"); }
}
function edit(row: Host): void { selected.value = row; label.value = row.label; address.value = row.address; port.value = String(row.port); enabled.value = row.is_enabled; }
function clear(): void { selected.value = null; label.value = ""; address.value = ""; port.value = String(props.configuration.listen_port); enabled.value = false; }
async function save(): Promise<void> {
  busy.value = true; error.value = "";
  try { await item<Host>(selected.value ? `/v1/admin/network/hosts/${selected.value.id}` : `/v1/admin/network/configurations/${props.configuration.id}/hosts`, selected.value ? "PUT" : "POST", { label: label.value, address: address.value, port: Number(port.value), is_enabled: enabled.value }); clear(); await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("configurationHosts.operationFailed"); } finally { busy.value = false; }
}
onMounted(load);
</script>
<template>
  <section style="margin-block:20px"><h3>{{ t("configurationHosts.title", { label: configuration.label }) }}</h3><p>{{ t("configurationHosts.description") }}</p><RouterLink class="btn small secondary" to="/host-groups">{{ t("configurationHosts.groups") }}</RouterLink><p v-if="error" class="message error" role="alert">{{ error }}</p>
  <form class="toolbar" @submit.prevent="page = 1; load()"><label class="field"><span>{{ t("configurationHosts.searchHosts") }}</span><input v-model="q" /></label><button class="btn secondary">{{ t("configurationHosts.search") }}</button></form>
  <div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t("configurationHosts.label") }}</th><th>{{ t("configurationHosts.address") }}</th><th>{{ t("configurationHosts.status") }}</th><th></th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.label }}</td><td dir="ltr">{{ row.address }}:{{ number(row.port, 0) }}</td><td>{{ t(row.is_enabled ? 'configurationHosts.enabled' : 'configurationHosts.inactive') }}</td><td><button v-if="auth.can('network', 'update')" class="btn small secondary" @click="edit(row)">{{ t("configurationHosts.editHost") }}</button></td></tr></tbody></table></div><p v-if="state === 'loading'">{{ t("configurationHosts.loading") }}</p><p v-else-if="state === 'ready' && !rows.length">{{ t("configurationHosts.empty") }}</p><button v-if="state === 'error'" class="btn secondary" @click="load">{{ t("configurationHosts.retry") }}</button><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages" @click="page++; load()">›</button></div>
  <form v-if="auth.can('network', selected ? 'update' : 'create')" class="form-grid" @submit.prevent="save"><h3>{{ selected ? t('configurationHosts.editSelected') : t('configurationHosts.createForConfiguration') }}</h3><label class="field"><span>{{ t("configurationHosts.label") }}</span><input v-model="label" required minlength="2" /></label><label class="field"><span>{{ t("configurationHosts.publicAddress") }}</span><input v-model="address" required dir="ltr" /></label><NumField v-model="port" :label="t('configurationHosts.publicPort')" /><label><input v-model="enabled" type="checkbox" /> {{ t("configurationHosts.available") }}</label><div class="inline-actions"><button class="btn" :disabled="busy">{{ t("configurationHosts.save") }}</button><button v-if="selected" type="button" class="btn secondary" @click="clear">{{ t("configurationHosts.create") }}</button></div></form></section>
</template>
