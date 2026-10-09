<script setup lang="ts">
import {onMounted,ref,watch} from "vue";
import {request,query,type Page,type PlanConfiguration} from "@papilio/api";
import {faNumber} from "@papilio/ui";
const props=withDefaults(defineProps<{planId:number;public?:boolean}>(),{public:false});
const rows=ref<PlanConfiguration[]>([]),loading=ref(false),error=ref(""),page=ref(1),pages=ref(1),total=ref(0);let sequence=0;
async function load():Promise<void>{const token=++sequence;loading.value=true;error.value="";try{const result=await request<Page<PlanConfiguration>>(`${props.public?'/v1/plans':'/v1/admin/plans'}/${props.planId}/configurations?${query({page:page.value})}`);if(token!==sequence)return;rows.value=result.data;pages.value=result.meta.pager?.total_pages??1;total.value=result.meta.pager?.total_items??0;}catch(cause){if(token===sequence)error.value=cause instanceof Error?cause.message:"Could not load the configuration bundle.";}finally{if(token===sequence)loading.value=false;}}
watch(()=>props.planId,()=>{page.value=1;rows.value=[];void load();});onMounted(load);
</script>
<template><section class="configuration-item"><h4>Connection options <span class="badge">{{faNumber(total)}}</span></h4><p v-if="error" class="message error" role="alert">{{error}}</p><p v-else-if="loading">Loading connection options…</p><p v-else-if="!rows.length">No connection options are listed for this plan.</p><div v-for="row in rows" :key="row.host_id" class="detail-line"><span>{{row.label}}</span><span class="bundle-tag">{{row.protocol}} <span v-if="!row.is_enabled">· disabled</span></span></div><div v-if="pages>1" class="pager"><button type="button" :disabled="loading||page<=1" @click="page--;load()">‹</button><span>{{faNumber(page)}} / {{faNumber(pages)}}</span><button type="button" :disabled="loading||page>=pages" @click="page++;load()">›</button></div></section></template>
