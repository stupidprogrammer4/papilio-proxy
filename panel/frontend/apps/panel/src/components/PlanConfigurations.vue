<script setup lang="ts">
import {onMounted,ref,watch} from "vue";
import {request,query,type Page,type PlanConfiguration} from "@papilio/api";
import {faNumber} from "@papilio/ui";
import {useI18n} from "vue-i18n";
const {t}=useI18n();
const props=withDefaults(defineProps<{planId:number;public?:boolean}>(),{public:false});
const rows=ref<PlanConfiguration[]>([]),loading=ref(false),error=ref(""),page=ref(1),pages=ref(1),total=ref(0);let sequence=0;
async function load():Promise<void>{const token=++sequence;loading.value=true;error.value="";try{const result=await request<Page<PlanConfiguration>>(`${props.public?'/v1/plans':'/v1/admin/plans'}/${props.planId}/configurations?${query({page:page.value})}`);if(token!==sequence)return;rows.value=result.data;pages.value=result.meta.pager?.total_pages??1;total.value=result.meta.pager?.total_items??0;}catch(cause){if(token===sequence)error.value=cause instanceof Error?cause.message:t("plans.configurations.loadError");}finally{if(token===sequence)loading.value=false;}}
watch(()=>props.planId,()=>{page.value=1;rows.value=[];void load();});onMounted(load);
</script>
<template><section class="configuration-item"><h4>{{t("plans.configurations.title")}} <span class="badge">{{faNumber(total)}}</span></h4><p v-if="error" class="message error" role="alert">{{error}}</p><p v-else-if="loading">{{t("plans.configurations.loading")}}</p><p v-else-if="!rows.length">{{t("plans.configurations.empty")}}</p><div v-for="row in rows" :key="row.host_id" class="detail-line"><span>{{row.label}}</span><span class="bundle-tag">{{row.protocol}} <span v-if="!row.is_enabled">· {{t("plans.configurations.disabled")}}</span></span></div><div v-if="pages>1" class="pager"><button type="button" :disabled="loading||page<=1" @click="page--;load()">‹</button><span>{{faNumber(page)}} / {{faNumber(pages)}}</span><button type="button" :disabled="loading||page>=pages" @click="page++;load()">›</button></div></section></template>
