<script setup lang="ts">
import type { SupportPolicy } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
import {useI18n} from "vue-i18n";
const model=defineModel<SupportPolicy>({required:true});
const {t}=useI18n();
const flags=[{key:"new_tickets_enabled",label:"new"},{key:"customer_replies_enabled",label:"customerReplies"},{key:"staff_replies_enabled",label:"staffReplies"},{key:"customer_closure_enabled",label:"close"},{key:"customer_reopen_enabled",label:"reopen"}] as const;
const sizes=[{key:"max_open_tickets",label:"openTickets"},{key:"max_messages_per_ticket",label:"messages"},{key:"max_message_chars",label:"characters"}] as const;
</script>
<template><div class="form-grid"><label v-for="flag in flags" :key="flag.key" class="support-flag"><input v-model="model[flag.key]" type="checkbox" />{{t(`settingsEditors.supportPolicy.${flag.label}`)}}</label><label class="field"><span>{{t('settingsEditors.supportPolicy.closed')}}</span><select v-model="model.closed_reply_mode" :aria-label="t('settingsEditors.supportPolicy.closed')"><option value="reject">{{t('settingsEditors.supportPolicy.reject')}}</option><option value="reopen">{{t('settingsEditors.supportPolicy.accept')}}</option></select></label><label class="field"><span>{{t('settingsEditors.supportPolicy.staffStatus')}}</span><select v-model="model.staff_reply_status" :aria-label="t('settingsEditors.supportPolicy.staffStatus')"><option value="open">{{t('settingsEditors.supportPolicy.open')}}</option><option value="waiting_customer">{{t('settingsEditors.supportPolicy.waiting')}}</option><option value="closed">{{t('settingsEditors.supportPolicy.closedStatus')}}</option></select></label><NumField v-for="size in sizes" :key="size.key" :label="t(`settingsEditors.supportPolicy.${size.label}`)" :model-value="String(model[size.key])" @update:model-value="model[size.key]=Number($event)" /><p class="hint-box">{{t('settingsEditors.supportPolicy.hint')}}</p></div></template>
<style scoped>.support-flag{display:flex;align-items:center;gap:8px}.support-flag input{width:auto;min-height:0}</style>
