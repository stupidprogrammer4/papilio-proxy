<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useResellerAuth } from "@papilio/auth";
import { item, type Reseller } from "@papilio/api";
import { faNumber } from "@papilio/ui";
import ResellerPolicyEditor from "../components/ResellerPolicyEditor.vue";
import { useI18n } from "vue-i18n";
const {t}=useI18n();
const auth=useResellerAuth(),profile=ref<Reseller|null>(null),loading=ref(false),error=ref("");
async function load():Promise<void>{loading.value=true;error.value="";try{profile.value=await item<Reseller>("/v1/reseller/profile");}catch(cause){error.value=cause instanceof Error?cause.message:t("resellerProfile.operationFailed");}finally{loading.value=false;}}
onMounted(()=>void load());
</script>
<template><div class="page-head"><div><p class="eyebrow">{{t('resellerProfile.eyebrow')}}</p><h1>{{auth.session?.title}}</h1><p class="subtitle">{{t('resellerProfile.description')}}</p></div><button class="btn secondary" :disabled="loading" @click="load">{{t('resellerProfile.refresh')}}</button></div><p v-if="error" class="message error">{{error}}</p><p v-if="loading">{{t('resellerProfile.loading')}}</p><section v-if="profile" class="card card-pad"><h2>{{t('resellerProfile.status')}}</h2><p>{{t('resellerProfile.revision',{revision:faNumber(profile.revision)})}} · {{profile.code}}</p><p>{{t('resellerProfile.signIn')}}: {{profile.login_enabled?t('resellerProfile.active'):t('resellerProfile.paused')}} · {{t('resellerProfile.sales')}}: {{profile.sales_enabled?t('resellerProfile.active'):t('resellerProfile.paused')}} · {{t('resellerProfile.renewal')}}: {{profile.renewals_enabled?t('resellerProfile.active'):t('resellerProfile.paused')}}</p><ResellerPolicyEditor v-model="profile.policy" disabled/></section></template>
