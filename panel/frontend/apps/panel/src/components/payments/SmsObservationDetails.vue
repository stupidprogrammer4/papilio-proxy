<script setup lang="ts">
import { type SmsProvenance, type SmsEvent } from "@papilio/api";
import { faDate, faNumber, toman } from "@papilio/ui";
defineProps<{provenance?:SmsProvenance|null;observation?:SmsEvent|null}>();
const originLabels = { direct_sms:"Direct SMS", forwarded:"Forwarded", imported:"Imported", manual:"Manual" };
function originalTime(value:number|null):string {
  if(value===null)return "Not recorded";
  const date=new Date(value);
  return Number.isFinite(date.getTime())?faDate(date.toISOString()):"Unavailable timestamp";
}
</script>
<template>
  <div v-if="!provenance&&!observation" class="hint-box">Captured source and parser evidence is unavailable for this SMS record.</div>
  <template v-if="observation">
    <p class="hint-box">These are captured observations. They do not establish current payment eligibility or independent bank settlement.</p>
    <dl class="evidence-grid" aria-label="Captured SMS observation">
      <div><dt>SMS record</dt><dd>#{{faNumber(observation.id)}}</dd></div>
      <div><dt>Sender time</dt><dd>{{faDate(observation.sent_at)}}</dd></div>
      <div><dt>Direction</dt><dd>{{observation.direction??'Legacy / not recorded'}}</dd></div>
      <div><dt>Deposit</dt><dd>{{observation.amount_rial===null?'Not identified':toman(observation.amount_rial)}}</dd></div>
      <div><dt>Balance</dt><dd>{{observation.balance_rial==null?'Not identified':toman(observation.balance_rial)}}</dd></div>
      <div><dt>Actual bank reference</dt><dd>{{observation.bank_reference??'Not recorded'}}</dd></div>
      <div><dt>Source device</dt><dd>{{observation.device_id==null?'Not recorded':'#'+observation.device_id}}</dd></div>
      <div><dt>Captured parser revision</dt><dd>{{observation.parser_revision_id==null?'Legacy / not recorded':'#'+observation.parser_revision_id}}</dd></div>
      <div><dt>Captured receiving account / alias</dt><dd>{{observation.receiving_realm_id==null?'Not recorded':'#'+observation.receiving_realm_id}} / {{observation.receiving_alias_id==null?'Not recorded':'#'+observation.receiving_alias_id}}</dd></div>
      <div><dt>Captured destination / revision</dt><dd>{{observation.captured_destination_id==null?'Not recorded':'#'+observation.captured_destination_id}} / {{observation.captured_destination_revision??'Not recorded'}}</dd></div>
      <div><dt>Declared source</dt><dd>{{observation.origin_kind==null?'Not recorded':originLabels[observation.origin_kind]}}</dd></div>
      <div><dt>Original provider time</dt><dd>{{originalTime(observation.original_provider_timestamp_ms??null)}}</dd></div>
      <div v-if="observation.origin_reason_code"><dt>Captured origin validation reason</dt><dd><code>{{observation.origin_reason_code}}</code></dd></div>
      <div v-if="observation.parse_reason_code"><dt>Parser reason</dt><dd><code>{{observation.parse_reason_code}}</code></dd></div>
    </dl>
    <details><summary>Captured evidence digests</summary><p>Parser definition: <code>{{observation.parser_definition_sha256??'Not recorded'}}</code></p><p>Original notification identity: <code>{{observation.declared_notification_sha256??'Not recorded'}}</code></p><p>Canonical message: <code>{{observation.canonical_message_digest??'Not recorded'}}</code></p><p>Origin identity: <code>{{observation.origin_identity_sha256??'Not recorded'}}</code></p><p>Canonicalization revision: {{observation.canonicalization_revision??'Not recorded'}}</p></details>
  </template>
  <dl v-if="provenance" class="evidence-grid" aria-label="Captured SMS evidence">
    <div><dt>Direction</dt><dd>{{provenance.direction??'Not recorded'}}</dd></div>
    <div><dt>Deposit</dt><dd>{{provenance.deposit_rial===null?'Not identified':toman(provenance.deposit_rial)}}</dd></div>
    <div><dt>Balance</dt><dd>{{provenance.balance_rial===null?'Not identified':toman(provenance.balance_rial)}}</dd></div>
    <div><dt>Actual bank reference</dt><dd>{{provenance.actual_bank_reference??'Not recorded'}}</dd></div>
    <div><dt>Captured parser revision</dt><dd>{{provenance.parser_revision_id===null?'Legacy / not recorded':faNumber(provenance.parser_revision_id)}}</dd></div>
    <div><dt>Declared source</dt><dd>{{provenance.origin_kind===null?'Not recorded':originLabels[provenance.origin_kind]}}</dd></div>
    <div><dt>Original provider time</dt><dd>{{originalTime(provenance.original_provider_timestamp_ms)}}</dd></div>
    <div><dt>Observed at</dt><dd>{{faDate(provenance.observed_at)}}</dd></div>
    <div><dt>Settlement record</dt><dd>{{provenance.settlement_id===null?'No linked settlement':faNumber(provenance.settlement_id)}}</dd></div>
    <div><dt>Evidence type</dt><dd>{{provenance.evidence_kind==='bank_reference'?'Bank reference':provenance.evidence_kind==='trusted_sms_origin'?'Trusted declared SMS origin':'Not recorded'}}</dd></div>
    <div v-if="provenance.reason_code"><dt>Recorded reason</dt><dd><code>{{provenance.reason_code}}</code></dd></div>
  </dl>
</template>
<style scoped>
.evidence-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:16px;margin:0}.evidence-grid dt{color:var(--muted);font-size:.85rem}.evidence-grid dd{margin:4px 0 0;overflow-wrap:anywhere}
</style>
