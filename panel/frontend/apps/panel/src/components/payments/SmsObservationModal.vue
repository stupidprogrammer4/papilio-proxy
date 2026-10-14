<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";
import { item, type SmsEvent, type SmsOriginCapabilities } from "@papilio/api";
import Modal from "@papilio/ui/Modal.vue";
import SmsSettlementReviewPanel from "./SmsSettlementReviewPanel.vue";
import SmsObservationDetails from "./SmsObservationDetails.vue";
import { useI18n } from "vue-i18n";
const props=defineProps<{eventId:number|null;capabilities:SmsOriginCapabilities|null}>();const open=defineModel<boolean>({required:true});
const { t } = useI18n();
const reviewBusy=ref(false);
const row=ref<SmsEvent|null>(null),loading=ref(false),error=ref("");let alive=true,sequence=0;
async function load():Promise<void>{const id=props.eventId;if(id===null)return;const key=++sequence;loading.value=true;error.value="";if(row.value?.id!==id)row.value=null;try{const result=await item<SmsEvent>(`/v1/admin/payments/sms/${id}`);if(alive&&key===sequence&&props.eventId===id)row.value=result;}catch(cause){if(alive&&key===sequence)error.value=cause instanceof Error?cause.message:t("errors.request_failed");}finally{if(alive&&key===sequence)loading.value=false;}}
watch(()=>[open.value,props.eventId],()=>{if(open.value)void load();else ++sequence;},{immediate:true});onUnmounted(()=>{alive=false;++sequence;});
</script>
<template><Modal v-model="open" :title="t('payments.sms.observation')" :eyebrow="t('payments.eyebrow')" :close-label="t('plans.closeDialog')" :busy="reviewBusy" wide><p v-if="loading" role="status">{{ t('payments.sms.loading') }}</p><p v-if="error" class="message error" role="alert">{{error}}</p><button class="btn secondary" :disabled="loading||reviewBusy" @click="load">{{ t('payments.sms.refresh') }}</button><SmsObservationDetails v-if="row" :observation="row"/><SmsSettlementReviewPanel v-if="row&&capabilities?.read_available" :event-id="row.id" :capabilities="capabilities" @busy="reviewBusy=$event"/></Modal></template>
