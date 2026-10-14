<script setup lang="ts">
import { useI18n } from "vue-i18n";
import Modal from "@papilio/ui/Modal.vue";
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuth } from "@papilio/auth";
import { item, query, request, type Page, type Staff, type StaffAccess, type StaffScopeCatalog } from "@papilio/api";
import { faNumber } from "@papilio/ui";
import StaffRoles from "../components/StaffRoles.vue";
import StaffScopeEditor from "../components/StaffScopeEditor.vue";
const { t } = useI18n();
const auth = useAuth(); const router = useRouter();const route=useRoute();
const rows = ref<Staff[]>([]); const q = ref(""); const page = ref(1); const pages = ref(1); const total = ref(0);
const selected = ref<StaffAccess | null>(null); const scopes = ref<string[]>([]); const active = ref(true); const password = ref("");
const username = ref(""); const newPassword = ref(""); const newScopes = ref<string[]>([]); const newActive = ref(true);
const catalog = ref<StaffScopeCatalog | null>(null); const loading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref("");
let readVersion = 0; let selectionVersion = 0;
function rolesUpdated(row: StaffAccess): void { if(selected.value?.id === row.id) selected.value=row; }
async function load(): Promise<void> {
  const version = ++readVersion; loading.value = true;
  try { const result = await request<Page<Staff>>(`/v1/admin/staff?${query({ q: q.value, page: page.value })}`); if (version !== readVersion) return; rows.value = result.data; pages.value = result.meta.pager?.total_pages ?? 1; total.value = result.meta.pager?.total_items ?? 0; }
  catch (cause) { if (version === readVersion) error.value = cause instanceof Error ? cause.message : t("staff.operationFailed"); }
  finally { if (version === readVersion) loading.value = false; }
}
async function select(row: Staff | number): Promise<void> {
  if (busy.value) return; const version = ++selectionVersion; error.value = "";
  selected.value = null; password.value = "";
  try { const result = await item<StaffAccess>(`/v1/admin/staff/${typeof row === "number" ? row : row.id}`); if (version !== selectionVersion) return; selected.value = result; scopes.value = [...result.scopes]; active.value = result.is_active; }
  catch (cause) { if (version === selectionVersion) error.value = cause instanceof Error ? cause.message : t("staff.operationFailed"); }
}
async function create(): Promise<void> {
  if (busy.value || !auth.can("staff", "create")) return; busy.value = true; error.value = ""; notice.value = "";
  try { const result = await item<StaffAccess>("/v1/admin/staff", "POST", { username: username.value.trim(), password: newPassword.value, is_active: newActive.value, scopes: newScopes.value }); username.value = ""; newPassword.value = ""; newScopes.value = []; selected.value = result; scopes.value = [...result.scopes]; active.value = result.is_active; notice.value = t("staff.created"); page.value = 1; await load(); createOpen.value=false; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("staff.operationFailed"); }
  finally { busy.value = false; }
}
async function save(): Promise<void> {
  const row = selected.value; if (!row || busy.value || !auth.can("staff", "update")) return; busy.value = true; error.value = ""; notice.value = "";
  try { const result = await item<StaffAccess>(`/v1/admin/staff/${row.id}/access`, "PUT", { is_active: active.value, scopes: scopes.value, expected_is_active: row.is_active, expected_scopes: row.scopes }); selected.value = result; notice.value = t("staff.accessSaved"); await load(); if(row.username === auth.session?.username) { await auth.restore(); if (!auth.session || !auth.can("staff")) await router.push(auth.session ? "/" : "/login"); } }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("staff.operationFailed"); }
  finally { busy.value = false; }
}
async function resetPassword(): Promise<void> {
  const row = selected.value; if (!row || busy.value || !auth.can("staff", "update")) return; busy.value = true; error.value = ""; notice.value = "";
  try { await request<void>(`/v1/admin/staff/${row.id}/password`, "PUT", { password: password.value }); password.value = ""; notice.value = t("staff.passwordChanged"); if (row.username === auth.session?.username) { await auth.restore(); await router.push("/login"); } }
  catch (cause) { error.value = cause instanceof Error ? cause.message : t("staff.operationFailed"); }
  finally { busy.value = false; }
}
watch(q, () => { page.value = 1; void load(); });
watch(()=>route.query.staff_id, id=>{if(typeof id==="string"&&/^\d+$/.test(id)&&Number(id)>0)void select(Number(id));});
  onMounted(async () => { if(typeof route.query.staff_id==="string"&&/^\d+$/.test(route.query.staff_id)&&Number(route.query.staff_id)>0)void select(Number(route.query.staff_id));void load(); try { catalog.value = await item<StaffScopeCatalog>("/v1/admin/staff/scope-catalog"); } catch(cause) { error.value = cause instanceof Error ? cause.message : t("staff.operationFailed"); } });
const createOpen=ref(false);
</script>
<template>
  <div class="page-head"><div><p class="eyebrow">{{ t('staff.eyebrow') }}</p><h1>{{ t('staff.title') }}</h1><p class="subtitle">{{ t('staff.description') }}</p></div><button class="btn secondary" :disabled="loading || busy" @click="error=''; load()">{{t("staff.refresh")}}</button><button v-if="auth.can('staff','create')" class="btn" :disabled="busy" @click="createOpen=true">+ {{t("staff.createButton")}}</button></div>
  <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
  <div :class="{split:!!selected}"><div class="card"><div class="card-pad"><label class="field"><span>{{t("staff.searchUsername")}}</span><input v-model="q" maxlength="64" /></label></div><div class="table-wrap"><table class="data-table"><thead><tr><th>{{t("staff.id")}}</th><th>{{t("staff.username")}}</th><th>{{t("staff.status")}}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id" :class="{'selected-row':selected?.id===row.id}" tabindex="0" @click="select(row)" @keydown.enter="select(row)"><td>{{ faNumber(row.id) }}</td><td dir="ltr">{{ row.username }}</td><td>{{ row.is_active ? t('staff.active') : t('staff.inactive') }}</td></tr></tbody></table><div v-if="loading" class="empty">{{t("staff.loading")}}</div><div v-else-if="!rows.length && !error" class="empty">{{t("staff.empty")}}</div></div><div class="pager"><button :disabled="page <= 1 || busy" @click="page--; load()">‹</button><span>{{ faNumber(page) }} · {{ faNumber(total) }} Staff</span><button :disabled="page >= pages || busy" @click="page++; load()">›</button></div></div>
    <div class="stack"><div v-if="selected" class="card card-pad"><h2>{{t("staff.account",{username:selected.username})}}</h2><p class="hint-box">{{t("staff.lastOwnerHint")}}</p><form v-if="auth.can('staff','update')" class="form-grid" @submit.prevent="save"><label class="scope-choice"><input v-model="active" type="checkbox" :disabled="busy" /> {{t("staff.accountEnabled")}}</label><StaffScopeEditor v-model="scopes" :catalog="catalog" :disabled="busy" /><button class="btn" :disabled="busy || !catalog">{{t("staff.saveAccess")}}</button><button type="button" class="btn secondary" :disabled="busy" @click="select(selected)">{{t("staff.reload")}}</button></form><p v-else class="hint-box">{{ selected.scopes.join(', ') || t('staff.noAccess') }}</p><StaffRoles :staff="selected" @updated="rolesUpdated" /><form v-if="auth.can('staff','update')" class="form-grid" style="margin-top:20px" @submit.prevent="resetPassword"><label class="field"><span>{{t("staff.newPassword")}}</span><input v-model="password" type="password" minlength="8" maxlength="256" autocomplete="new-password" required :disabled="busy" /></label><button class="btn secondary" :disabled="busy || password.length < 8">{{t("staff.changePassword")}}</button></form></div>
      <Modal v-if="auth.can('staff','create')" v-model="createOpen" :title="t('staff.createTitle')" :busy="busy" wide><p v-if="error" class="message error" role="alert">{{error}}</p><form class="form-grid" @submit.prevent="create"><label class="field"><span>{{t("staff.username")}}</span><input v-model="username" minlength="3" maxlength="64" required :disabled="busy" /></label><label class="field"><span>{{t("staff.password")}}</span><input v-model="newPassword" type="password" minlength="8" maxlength="256" autocomplete="new-password" required :disabled="busy" /></label><label class="scope-choice"><input v-model="newActive" type="checkbox" :disabled="busy" /> {{t("staff.accountEnabled")}}</label><StaffScopeEditor v-model="newScopes" :catalog="catalog" :disabled="busy" /><button class="btn" :disabled="busy || !catalog || username.trim().length < 3 || newPassword.length < 8">{{t("staff.create")}}</button></form></Modal>
    </div>
  </div>
</template>
<style scoped>
.scope-choice { display:flex; align-items:center; gap:8px; }
.scope-choice input { width:auto; min-height:0; }
</style>
