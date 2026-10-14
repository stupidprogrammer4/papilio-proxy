<script setup lang="ts">
import { onMounted,ref } from "vue";
import { item,type ResellerDefaults,type StaffScopeCatalog } from "@papilio/api";
import { useAuth } from "@papilio/auth";
import ResellerPolicyEditor from "./ResellerPolicyEditor.vue";
import StaffScopeEditor from "./StaffScopeEditor.vue";
import {useI18n} from "vue-i18n";
const values=defineModel<ResellerDefaults>({required:true});
const props=defineProps<{disabled?:boolean}>();
const auth=useAuth(),catalog=ref<StaffScopeCatalog|null>(null),error=ref("");
const {t}=useI18n();
async function load():Promise<void>{error.value="";try{catalog.value=await item<StaffScopeCatalog>("/v1/admin/resellers/scope-catalog");}catch(cause){error.value=cause instanceof Error?cause.message:"The operation failed. Please try again.";}}
onMounted(()=>{if(auth.can("resellers"))void load();});
</script>
<template><section class="form-grid"><h3>{{t('settingsEditors.resellerDefaults.title')}}</h3><p class="hint-box">{{t('settingsEditors.resellerDefaults.hint')}}</p><label class="check-row"><input v-model="values.access.login_enabled" type="checkbox" :disabled="props.disabled"/>{{t('settingsEditors.resellerDefaults.signin')}}</label><label class="check-row"><input v-model="values.access.sales_enabled" type="checkbox" :disabled="props.disabled"/>{{t('settingsEditors.resellerDefaults.sales')}}</label><label class="check-row"><input v-model="values.access.renewals_enabled" type="checkbox" :disabled="props.disabled"/>{{t('settingsEditors.resellerDefaults.renewals')}}</label><label class="check-row"><input v-model="values.owner_is_active" type="checkbox" :disabled="props.disabled"/>{{t('settingsEditors.resellerDefaults.owner')}}</label><p v-if="error" class="message error">{{error}} <button type="button" class="btn secondary" @click="load">{{t('settingsEditors.resellerDefaults.retry')}}</button></p><StaffScopeEditor v-if="catalog" v-model="values.owner_access.scopes" :catalog="catalog" :grants="['*']" :owner-label="t('settingsEditors.resellerDefaults.ownerFull')" :disabled="props.disabled"/><p v-else class="hint-box">{{t('settingsEditors.resellerDefaults.catalog')}}</p><ResellerPolicyEditor v-model="values.policy" :disabled="props.disabled"/><h4>{{t('settingsEditors.resellerDefaults.wallet')}}</h4><label class="check-row"><input v-model="values.wallet_customer_access.is_active" type="checkbox" :disabled="props.disabled"/>{{t('settingsEditors.resellerDefaults.account')}}</label><label class="check-row"><input v-model="values.wallet_customer_access.services_enabled" type="checkbox" :disabled="props.disabled"/>{{t('settingsEditors.resellerDefaults.purchase')}}</label><label class="check-row"><input v-model="values.wallet_customer_access.renewals_enabled" type="checkbox" :disabled="props.disabled"/>{{t('settingsEditors.resellerDefaults.walletRenewal')}}</label></section></template>
