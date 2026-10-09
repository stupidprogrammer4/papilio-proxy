<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { useResellerAuth } from "@papilio/auth";
import { item, type Reseller } from "@papilio/api";
import ResellerTeam from "../components/ResellerTeam.vue";
const route=useRoute(),auth=useResellerAuth();
const admin=computed(()=>!route.meta.reseller), parent=ref<Reseller|null>(null), error=ref("");
const resellerId=computed(()=>Number(route.params.resellerId));
async function loadParent():Promise<void>{error.value="";try{parent.value=await item<Reseller>(`/v1/admin/resellers/${resellerId.value}`);}catch(cause){error.value=cause instanceof Error?cause.message:"The operation failed. Please try again.";}}
onMounted(()=>{if(admin.value)void loadParent();});
</script>
<template><div class="page-head"><div><p class="eyebrow">TEAM ACCESS</p><h1>Team for {{admin?parent?.title:auth.session?.title}}</h1><p class="subtitle">Manage member permissions within this reseller account.</p></div><RouterLink v-if="admin" to="/resellers" class="btn secondary">Resellers</RouterLink></div><p v-if="error" class="message error">{{error}} <button class="btn secondary" @click="loadParent">Retry</button></p><ResellerTeam v-if="!admin||parent" :realm="admin?'admin':'reseller'" :reseller-id="admin?parent?.id:undefined"/><p v-else-if="!error">Loading reseller account…</p></template>
