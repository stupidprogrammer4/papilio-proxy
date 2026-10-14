<script setup lang="ts">
import { useI18n } from "vue-i18n";
import Modal from "@papilio/ui/Modal.vue";
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { item, request, query, type HostGroup, type Page } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import { faNumber } from "@papilio/ui";
import GroupMembers from "../components/GroupMembers.vue";
const { t } = useI18n();
const route=useRoute();
const auth = useAuth(); const rows = ref<HostGroup[]>([]); const page = ref(1); const pages = ref(1); const q = ref(""); const state = ref<"loading" | "ready" | "error">("loading"); const error = ref(""); const busy = ref(false);
const selected = ref<HostGroup | null>(null); const code = ref(""); const title = ref(""); const enabled = ref(false);
async function load(): Promise<void> {
  state.value = "loading"; error.value = ""; const requested = page.value;
  try { const result = await request<Page<HostGroup>>(`/v1/admin/network/host-groups?${query({ page: requested, q: q.value })}`); if (requested !== page.value) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; state.value = "ready"; }
  catch (cause) { state.value = "error"; error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
}
function choose(row: HostGroup): void { if(busy.value)return;selected.value = row; code.value = row.code; title.value = row.title; enabled.value = row.is_enabled; }
function clear(): void { if(busy.value)return;selected.value = null; code.value = ""; title.value = ""; enabled.value = false; }
async function save(): Promise<void> {
  busy.value = true; error.value = "";
  try { const result = await item<HostGroup>(selected.value ? `/v1/admin/network/host-groups/${selected.value.id}` : "/v1/admin/network/host-groups", selected.value ? "PUT" : "POST", { code: code.value, title: title.value, is_enabled: enabled.value }); selected.value=result;createOpen.value=false;await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; } finally { busy.value = false; }
}
async function selectRoute():Promise<void>{const id=Number(route.query.group_id);if(!Number.isSafeInteger(id)||id<=0)return;try{const row=await item<HostGroup>(`/v1/admin/network/host-groups/${id}`);if(Number(route.query.group_id)===id)choose(row);}catch(cause){error.value=cause instanceof Error?cause.message:"Could not load the delivery group.";}}
watch(()=>route.query.group_id,selectRoute);
onMounted(()=>{void load();void selectRoute();});
const createOpen=ref(false);
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">{{ t('hostGroups.eyebrow') }}</p><h1>{{ t('hostGroups.title') }}</h1><p class="subtitle">{{ t('hostGroups.description') }}</p></div><button v-if="auth.can('network','create')" class="btn" :disabled="busy" @click="clear();createOpen=true">{{ t('hostGroupsAdmin.create') }}</button></div><p v-if="error" class="message error" role="alert">{{ error }}</p>
  <div><section class="card card-pad"><form class="toolbar" @submit.prevent="page = 1; load()"><label class="field"><span>{{ t('hostGroupsAdmin.searchGroups') }}</span><input v-model="q" /></label><button class="btn secondary">{{ t('hostGroupsAdmin.search') }}</button></form><div class="table-wrap"><table class="data-table"><thead><tr><th>{{ t('hostGroupsAdmin.titleColumn') }}</th><th>{{ t('hostGroupsAdmin.code') }}</th><th>{{ t('hostGroupsAdmin.status') }}</th><th></th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.title }}</td><td>{{ row.code }}</td><td>{{ t(row.is_enabled ? 'hostGroupsAdmin.enabled' : 'hostGroupsAdmin.inactive') }}</td><td><button class="btn small secondary" @click="choose(row)">{{ t('hostGroupsAdmin.manageMembers') }}</button></td></tr></tbody></table></div><p v-if="state === 'loading'">{{ t('hostGroupsAdmin.loading') }}</p><p v-else-if="state === 'ready' && !rows.length">{{ t('hostGroupsAdmin.empty') }}</p><button v-if="state === 'error'" class="btn secondary" @click="load">{{ t('hostGroupsAdmin.retry') }}</button><div class="pager"><button :disabled="page <= 1" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages" @click="page++; load()">›</button></div></section>
  <Modal v-if="auth.can('network', selected ? 'update' : 'create')" v-model="createOpen" :title="selected?t('hostGroupsAdmin.editTitle'):t('hostGroupsAdmin.createTitle')" :busy="busy" wide><p v-if="error" class="message error" role="alert">{{error}}</p><form class="form-grid" @submit.prevent="save"><label class="field"><span>{{ t('hostGroupsAdmin.groupCode') }}</span><input v-model="code" required minlength="2" pattern="[A-Za-z0-9_-]+" dir="ltr" /></label><label class="field"><span>{{ t('hostGroupsAdmin.groupTitle') }}</span><input v-model="title" required minlength="2" /></label><label><input v-model="enabled" type="checkbox" /> {{ t('hostGroupsAdmin.available') }}</label><button class="btn" :disabled="busy">{{ t('hostGroupsAdmin.save') }}</button></form></Modal></div>
  <section v-if="selected" class="card card-pad"><div class="page-head"><div><h2>{{selected.title}}</h2><p>{{selected.code}} · {{t(selected.is_enabled?'hostGroupsAdmin.enabled':'hostGroupsAdmin.disabled')}}</p></div><button v-if="auth.can('network','update')" class="btn secondary" :disabled="busy" @click="createOpen=true">{{ t('hostGroupsAdmin.edit') }}</button></div></section>
  <GroupMembers v-if="selected" :key="selected.id" :group="selected" />
</template>
