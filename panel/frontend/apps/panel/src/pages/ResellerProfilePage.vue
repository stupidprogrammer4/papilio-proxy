<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useResellerAuth } from "@papilio/auth";
import { item, type Reseller } from "@papilio/api";
import { faNumber } from "@papilio/ui";
import ResellerPolicyEditor from "../components/ResellerPolicyEditor.vue";
const auth=useResellerAuth(),profile=ref<Reseller|null>(null),loading=ref(false),error=ref("");
async function load():Promise<void>{loading.value=true;error.value="";try{profile.value=await item<Reseller>("/v1/reseller/profile");}catch(cause){error.value=cause instanceof Error?cause.message:"The operation failed. Please try again.";}finally{loading.value=false;}}
onMounted(()=>void load());
</script>
<template><div class="page-head"><div><p class="eyebrow">Reseller account</p><h1>{{auth.session?.title}}</h1><p class="subtitle">Review your current policy and permissions.</p></div><button class="btn secondary" :disabled="loading" @click="load">Refresh</button></div><p v-if="error" class="message error">{{error}}</p><p v-if="loading">Loading…</p><section v-if="profile" class="card card-pad"><h2>Reseller status</h2><p>Revision {{faNumber(profile.revision)}} · {{profile.code}}</p><p>Sign in: {{profile.login_enabled?'Active':'Paused'}} · Sales: {{profile.sales_enabled?'Active':'Paused'}} · Renewal: {{profile.renewals_enabled?'Active':'Paused'}}</p><ResellerPolicyEditor v-model="profile.policy" disabled/></section></template>
