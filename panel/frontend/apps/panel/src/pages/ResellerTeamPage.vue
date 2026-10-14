<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { useResellerAuth } from "@papilio/auth";
import { item, type Reseller } from "@papilio/api";
import ResellerTeam from "../components/ResellerTeam.vue";
import { useI18n } from "vue-i18n";
const {t}=useI18n();
const route=useRoute(),auth=useResellerAuth();
const admin=computed(()=>!route.meta.reseller), parent=ref<Reseller|null>(null), error=ref("");
const resellerId=computed(()=>Number(route.params.resellerId));
async function loadParent():Promise<void>{error.value="";try{parent.value=await item<Reseller>(`/v1/admin/resellers/${resellerId.value}`);}catch(cause){error.value=cause instanceof Error?cause.message:t("resellerTeamPage.loadFailed");}}
onMounted(()=>{if(admin.value)void loadParent();});
</script>
<template><div class="page-head"><div><p class="eyebrow">{{t('resellerTeamPage.eyebrow')}}</p><h1>{{t('resellerTeamPage.title',{name:admin?parent?.title:auth.session?.title})}}</h1><p class="subtitle">{{t('resellerTeamPage.description')}}</p></div><RouterLink v-if="admin" to="/resellers" class="btn secondary">{{t('resellerTeamPage.resellers')}}</RouterLink></div><p v-if="error" class="message error">{{error}} <button class="btn secondary" @click="loadParent">{{t('resellerTeamPage.retry')}}</button></p><ResellerTeam v-if="!admin||parent" :realm="admin?'admin':'reseller'" :reseller-id="admin?parent?.id:undefined"/><p v-else-if="!error">{{t('resellerTeamPage.loading')}}</p></template>
