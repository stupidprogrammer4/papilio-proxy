<script setup lang="ts">
import { computed } from "vue";
import { type SmsProvenance, type SmsEvent } from "@papilio/api";
import { faNumber } from "@papilio/ui";
import { useI18n } from "vue-i18n";
import { useLocalizedFormats } from "../../composables/useLocalizedFormats";
defineProps<{provenance?:SmsProvenance|null;observation?:SmsEvent|null}>();
const { t } = useI18n();
const { date: formatDate, toman: formatToman } = useLocalizedFormats();
const originLabels = computed(() => ({ direct_sms:t("payments.sms.direct"), forwarded:t("payments.sms.forwarded"), imported:t("payments.sms.imported"), manual:t("payments.sms.manual") }));
function directionLabel(value:string|null|undefined):string {
  if(value==="credit")return t("payments.sms.credit");
  if(value==="debit")return t("payments.sms.debit");
  return value??t("payments.sms.notRecorded");
}
function originalTime(value:number|null):string {
  if(value===null)return t("payments.sms.notRecorded");
  const parsed=new Date(value);
  return Number.isFinite(parsed.getTime())?formatDate(parsed.toISOString()):t("payments.sms.unavailableTime");
}
</script>
<template>
  <div v-if="!provenance&&!observation" class="hint-box">{{ t("payments.sms.unavailable") }}</div>
  <template v-if="observation">
    <p class="hint-box">{{ t("payments.sms.capturedHint") }}</p>
    <dl class="evidence-grid" :aria-label="t('payments.sms.capturedLabel')">
      <div><dt>{{ t("payments.sms.record") }}</dt><dd>#{{faNumber(observation.id)}}</dd></div>
      <div><dt>{{ t("payments.sms.senderTime") }}</dt><dd>{{formatDate(observation.sent_at)}}</dd></div>
      <div><dt>{{ t("payments.sms.direction") }}</dt><dd>{{observation.direction===null?t('payments.sms.legacy'):directionLabel(observation.direction)}}</dd></div>
      <div><dt>{{ t("payments.sms.deposit") }}</dt><dd>{{observation.amount_rial===null?t('payments.sms.notIdentified'):formatToman(observation.amount_rial)}}</dd></div>
      <div><dt>{{ t("payments.sms.balance") }}</dt><dd>{{observation.balance_rial==null?t('payments.sms.notIdentified'):formatToman(observation.balance_rial)}}</dd></div>
      <div><dt>{{ t("payments.sms.actualReference") }}</dt><dd>{{observation.bank_reference??t('payments.sms.notRecorded')}}</dd></div>
      <div><dt>{{ t("payments.sms.sourceDevice") }}</dt><dd>{{observation.device_id==null?t('payments.sms.notRecorded'):'#'+observation.device_id}}</dd></div>
      <div><dt>{{ t("payments.sms.parserRevision") }}</dt><dd>{{observation.parser_revision_id==null?t('payments.sms.legacy'):'#'+observation.parser_revision_id}}</dd></div>
      <div><dt>{{ t("payments.sms.receivingAccountAlias") }}</dt><dd>{{observation.receiving_realm_id==null?t('payments.sms.notRecorded'):'#'+observation.receiving_realm_id}} / {{observation.receiving_alias_id==null?t('payments.sms.notRecorded'):'#'+observation.receiving_alias_id}}</dd></div>
      <div><dt>{{ t("payments.sms.destinationRevision") }}</dt><dd>{{observation.captured_destination_id==null?t('payments.sms.notRecorded'):'#'+observation.captured_destination_id}} / {{observation.captured_destination_revision??t('payments.sms.notRecorded')}}</dd></div>
      <div><dt>{{ t("payments.sms.declaredSource") }}</dt><dd>{{observation.origin_kind==null?t('payments.sms.notRecorded'):originLabels[observation.origin_kind]}}</dd></div>
      <div><dt>{{ t("payments.sms.originalTime") }}</dt><dd>{{originalTime(observation.original_provider_timestamp_ms??null)}}</dd></div>
      <div v-if="observation.origin_reason_code"><dt>{{ t("payments.sms.originReason") }}</dt><dd><code>{{observation.origin_reason_code}}</code></dd></div>
      <div v-if="observation.parse_reason_code"><dt>{{ t("payments.sms.parserReason") }}</dt><dd><code>{{observation.parse_reason_code}}</code></dd></div>
    </dl>
    <details><summary>{{ t("payments.sms.digests") }}</summary><p>{{ t("payments.sms.parserDefinition") }}: <code>{{observation.parser_definition_sha256??t('payments.sms.notRecorded')}}</code></p><p>{{ t("payments.sms.notificationIdentity") }}: <code>{{observation.declared_notification_sha256??t('payments.sms.notRecorded')}}</code></p><p>{{ t("payments.sms.canonicalMessage") }}: <code>{{observation.canonical_message_digest??t('payments.sms.notRecorded')}}</code></p><p>{{ t("payments.sms.originIdentity") }}: <code>{{observation.origin_identity_sha256??t('payments.sms.notRecorded')}}</code></p><p>{{ t("payments.sms.canonicalizationRevision") }}: {{observation.canonicalization_revision??t('payments.sms.notRecorded')}}</p></details>
  </template>
  <dl v-if="provenance" class="evidence-grid" :aria-label="t('payments.sms.capturedEvidenceLabel')">
    <div><dt>{{ t("payments.sms.direction") }}</dt><dd>{{directionLabel(provenance.direction)}}</dd></div>
    <div><dt>{{ t("payments.sms.deposit") }}</dt><dd>{{provenance.deposit_rial===null?t('payments.sms.notIdentified'):formatToman(provenance.deposit_rial)}}</dd></div>
    <div><dt>{{ t("payments.sms.balance") }}</dt><dd>{{provenance.balance_rial===null?t('payments.sms.notIdentified'):formatToman(provenance.balance_rial)}}</dd></div>
    <div><dt>{{ t("payments.sms.actualReference") }}</dt><dd>{{provenance.actual_bank_reference??t('payments.sms.notRecorded')}}</dd></div>
    <div><dt>{{ t("payments.sms.parserRevision") }}</dt><dd>{{provenance.parser_revision_id===null?t('payments.sms.legacy'):faNumber(provenance.parser_revision_id)}}</dd></div>
    <div><dt>{{ t("payments.sms.declaredSource") }}</dt><dd>{{provenance.origin_kind===null?t('payments.sms.notRecorded'):originLabels[provenance.origin_kind]}}</dd></div>
    <div><dt>{{ t("payments.sms.originalTime") }}</dt><dd>{{originalTime(provenance.original_provider_timestamp_ms)}}</dd></div>
    <div><dt>{{ t("payments.settlement.lastChecked") }}</dt><dd>{{formatDate(provenance.observed_at)}}</dd></div>
    <div><dt>{{ t("payments.settlement.linkedPayment") }}</dt><dd>{{provenance.settlement_id===null?t('payments.sms.noSettlement'):faNumber(provenance.settlement_id)}}</dd></div>
    <div><dt>{{ t("payments.sms.evidenceType") }}</dt><dd>{{provenance.evidence_kind==='bank_reference'?t('payments.sms.bankEvidence'):provenance.evidence_kind==='trusted_sms_origin'?t('payments.sms.trustedEvidence'):t('payments.sms.notRecorded')}}</dd></div>
    <div v-if="provenance.reason_code"><dt>{{ t("payments.sms.recordedReason") }}</dt><dd><code>{{provenance.reason_code}}</code></dd></div>
  </dl>
</template>
<style scoped>
.evidence-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:16px;margin:0}.evidence-grid dt{color:var(--muted);font-size:.85rem}.evidence-grid dd{margin:4px 0 0;overflow-wrap:anywhere}
</style>
