<script setup lang="ts">
import { onMounted, ref } from "vue";
import { item, query, request, type Host, type HostGroup, type GroupHost, type HostMembership, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faNumber } from "@papilio/ui";
import NumField from "@papilio/ui/NumField.vue";
import { useI18n } from "vue-i18n";
const props = defineProps<{ group: HostGroup }>(); const auth = useAuth(); const { t } = useI18n();
const rows = ref<GroupHost[]>([]); const page = ref(1); const pages = ref(1); const state = ref<"loading" | "ready" | "error">("loading");
const hosts = ref<Host[]>([]); const hostPage = ref(1); const hostPages = ref(1); const q = ref(""); const hostState = ref<"idle" | "loading" | "ready" | "error">("idle");
const selected = ref<Host | null>(null); const error = ref(""); const busy = ref(false); const removing = ref<number | null>(null);
const label = ref(""); const address = ref(""); const port = ref(""); const serverName = ref(""); const enabled = ref(true); const sortOrder = ref("");
async function load(): Promise<void> {
  state.value = "loading"; error.value = ""; const requested = page.value;
  try { const result = await request<Page<GroupHost>>(`/v1/admin/network/host-groups/${props.group.id}/hosts?${query({ page: requested })}`); if (page.value !== requested) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; state.value = "ready"; }
  catch (cause) { state.value = "error"; error.value = cause instanceof Error ? cause.message : t("groupMembers.operationFailed"); }
}
async function search(): Promise<void> {
  hostState.value = "loading"; error.value = ""; const requested = hostPage.value;
  try { const result = await request<Page<Host>>(`/v1/admin/network/hosts?${query({ q: q.value, page: requested })}`); if (hostPage.value !== requested) return; hosts.value = result.data; hostPages.value = result.meta.pager?.total_pages ?? 1; hostState.value = "ready"; }
  catch (cause) { hostState.value = "error"; error.value = cause instanceof Error ? cause.message : t("groupMembers.operationFailed"); }
}
function choose(host: Host, existing?: GroupHost): void {
  selected.value = host; removing.value = null; label.value = existing?.membership.label ?? ""; address.value = existing?.membership.address ?? ""; port.value = existing?.membership.port?.toString() ?? ""; serverName.value = existing?.membership.server_name ?? ""; enabled.value = existing?.membership.is_enabled ?? true; sortOrder.value = existing?.membership.sort_order.toString() ?? "0";
}
async function chooseTarget(host: Host): Promise<void> {
  selected.value = host; error.value = ""; busy.value = true;
  try { const result = await item<{ membership: HostMembership | null }>(`/v1/admin/network/host-groups/${props.group.id}/hosts/${host.id}`); if (selected.value?.id !== host.id) return; choose(host, result.membership ? { host, membership: result.membership } : undefined); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("groupMembers.operationFailed"); }
  finally { busy.value = false; }
}
async function save(): Promise<void> {
  if (!selected.value) return; busy.value = true; error.value = "";
  try { await item(`/v1/admin/network/host-groups/${props.group.id}/hosts/${selected.value.id}`, "PUT", { label: label.value.trim() || null, address: address.value.trim() || null, port: port.value ? Number(port.value) : null, server_name: serverName.value.trim() || null, is_enabled: enabled.value, sort_order: Number(sortOrder.value) }); await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("groupMembers.operationFailed"); } finally { busy.value = false; }
}
async function remove(hostId: number): Promise<void> {
  busy.value = true; error.value = "";
  try { await request(`/v1/admin/network/host-groups/${props.group.id}/hosts/${hostId}`, "DELETE"); if (selected.value?.id === hostId) selected.value = null; removing.value = null; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("groupMembers.operationFailed"); } finally { busy.value = false; }
}
onMounted(load);
</script>
<template>
  <section class="card card-pad" style="margin-top:18px"><h2>{{t('groupMembers.title',{group:group.title})}}</h2><p v-if="error" class="message error" role="alert">{{ error }}</p><p class="hint-box">{{t('groupMembers.description')}}</p>
  <button class="btn small secondary" @click="load">{{t('groupMembers.refresh')}}</button><div class="table-wrap"><table class="data-table"><thead><tr><th>{{t('groupMembers.host')}}</th><th>{{t('groupMembers.address')}}</th><th>{{t('groupMembers.nameOrder')}}</th><th>{{t('groupMembers.status')}}</th><th></th></tr></thead><tbody><tr v-for="row in rows" :key="row.membership.id"><td>{{ row.host.label }}</td><td dir="ltr">{{ row.membership.address ?? row.host.address }}:{{ faNumber(row.membership.port ?? row.host.port) }}</td><td>{{ row.membership.label ?? row.host.label }} / {{ faNumber(row.membership.sort_order) }}</td><td>{{ row.membership.is_enabled && row.host.is_enabled && group.is_enabled ? t('groupMembers.enabled') : t('groupMembers.inactive') }}</td><td><button v-if="auth.can('network', 'update')" class="btn small secondary" :disabled="busy" @click="choose(row.host, row)">{{t('groupMembers.settings')}}</button><button v-if="auth.can('network', 'delete')" class="btn small secondary" :disabled="busy" @click="removing = row.host.id">{{t('groupMembers.remove')}}</button><div v-if="removing === row.host.id"><span>{{t('groupMembers.confirmRemove')}}</span><button class="btn small" @click="remove(row.host.id)">{{t('groupMembers.confirm')}}</button><button class="btn small secondary" @click="removing = null">{{t('groupMembers.cancel')}}</button></div></td></tr></tbody></table></div><p v-if="state === 'loading'">{{t('groupMembers.loading')}}</p><p v-else-if="state === 'ready' && !rows.length">{{t('groupMembers.empty')}}</p><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages" @click="page++; load()">›</button></div>
  <template v-if="auth.can('network', 'update')"><h3>{{t('groupMembers.addHost')}}</h3><form class="toolbar" @submit.prevent="hostPage = 1; search()"><label class="field"><span>{{t('groupMembers.searchHost')}}</span><input v-model="q" /></label><button class="btn secondary">{{t('groupMembers.findHosts')}}</button></form><div class="inline-actions"><button v-for="host in hosts" :key="host.id" class="btn small secondary" :disabled="busy" :aria-pressed="selected?.id === host.id" @click="chooseTarget(host)">{{ host.label }} · {{ host.address }}</button></div><p v-if="hostState === 'loading'">{{t('groupMembers.loadingHosts')}}</p><p v-else-if="hostState === 'ready' && !hosts.length">{{t('groupMembers.noHosts')}}</p><div v-if="hostState !== 'idle'" class="pager"><button :disabled="hostPage <= 1" @click="hostPage--; search()">‹</button><span>{{ faNumber(hostPage) }}</span><button :disabled="hostPage >= hostPages" @click="hostPage++; search()">›</button></div>
  <form v-if="selected" class="form-grid" @submit.prevent="save"><fieldset :disabled="busy" class="form-grid"><h3>{{t('groupMembers.settingsTitle',{host:selected.label,group:group.title})}}</h3><label class="field"><span>{{t('groupMembers.nameOverride')}}</span><input v-model="label" /></label><label class="field"><span>{{t('groupMembers.addressOverride')}}</span><input v-model="address" dir="ltr" /></label><NumField v-model="port" :label="t('groupMembers.portOverride')" /><label class="field"><span>{{t('groupMembers.tlsName')}}</span><input v-model="serverName" dir="ltr" /></label><NumField v-model="sortOrder" signed :label="t('groupMembers.order')" /><label><input v-model="enabled" type="checkbox" /> {{t('groupMembers.membershipEnabled')}}</label><button class="btn" :disabled="busy">{{t('groupMembers.save')}}</button></fieldset></form></template></section>
</template>

<style scoped>
fieldset { border: 0; margin: 0; padding: 0; min-inline-size: 0; }
</style>
