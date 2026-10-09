<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import Modal from "@papilio/ui/Modal.vue";
import { item, query, request, type NodeAdapterCapability, type NodeCapabilityLatest, type NodeCapabilityObservation, type NodeEndpoint, type NodeOperationCapability, type Page } from "@papilio/api";
import { faDate } from "@papilio/ui";

const props=defineProps<{open:boolean;node:NodeEndpoint|null}>();
const emit=defineEmits<{close:[]}>();
const latest=ref<NodeCapabilityLatest|null>(null),selected=ref<NodeCapabilityObservation|null>(null),rows=ref<NodeCapabilityObservation[]>([]);
const latestState=ref<"loading"|"ready"|"error">("loading"),historyState=ref<"loading"|"ready"|"error">("loading");
const latestError=ref(""),historyError=ref(""),page=ref(1),pages=ref(1),total=ref(0);
let version=0,latestVersion=0,historyVersion=0;
const selectedIsLatest=computed(()=>selected.value?.observation_id===latest.value?.observation?.observation_id);
const operations:{key:Exclude<keyof NodeAdapterCapability,"kind"|"adapter_revision"|"executable">;label:string}[]=[
 {key:"validation",label:"Document validation"},{key:"installation",label:"Installation adapter"},{key:"installed_membership",label:"Installed membership"},
 {key:"counters",label:"Usage counters"},{key:"polled_stop",label:"Polling and whole-core stop"},{key:"strict_quota_expiry",label:"Strict quota and expiry"},
 {key:"ip_admission",label:"Source IP admission"},{key:"device_admission",label:"Device admission"},{key:"final_counters",label:"Final counter barrier"},{key:"protocol_matrix",label:"Protocol compatibility matrix"},
];
const adapterNames={xray:"Xray",sing_box:"sing-box",openvpn:"OpenVPN",wireguard:"WireGuard",hysteria:"Hysteria"};
function compatibility(value:NodeOperationCapability):string{return value.compatibility==="reference_match"?"Reported reference match":value.compatibility==="unverified"?"Compatibility unverified":"Unavailable";}
function failure(cause:unknown):string{return cause instanceof Error?cause.message:"Could not load node capability reports. Retry the request.";}
function assertOwner(row:NodeCapabilityObservation,nodeId:number):void{if(row.node_id!==nodeId||row.evidence_kind!=="authenticated_node_self_report"||row.report.schema_revision!==1)throw new Error("The report does not match this node or its supported evidence contract.");}
async function loadLatest():Promise<void>{
 if(!props.node)return;
 const stamp=version,attempt=++latestVersion,nodeId=props.node.id;
 latestState.value="loading";latestError.value="";
 try{
  const value=await item<NodeCapabilityLatest>(`/v1/admin/network/nodes/${nodeId}/capabilities/latest`);
  if(stamp!==version||attempt!==latestVersion)return;
  if(value.node_id!==nodeId)throw new Error("The capability result belongs to a different node.");
  if((value.status==="absent")!==(value.observation===null))throw new Error("The report freshness result is inconsistent. Retry before relying on it.");
  if(value.observation)assertOwner(value.observation,nodeId);
  const followLatest=!selected.value||selectedIsLatest.value;
  latest.value=value;if(followLatest)selected.value=value.observation;
  latestState.value="ready";
 }catch(cause){if(stamp===version&&attempt===latestVersion){latestError.value=failure(cause);latestState.value="error";}}
}
async function loadHistory(target=page.value):Promise<void>{
 if(!props.node)return;
 const stamp=version,attempt=++historyVersion,nodeId=props.node.id;
 historyState.value="loading";historyError.value="";
 try{
  const value=await request<Page<NodeCapabilityObservation>>(`/v1/admin/network/nodes/${nodeId}/capabilities/history?${query({page:target})}`);
  if(stamp!==version||attempt!==historyVersion)return;
  value.data.forEach(row=>assertOwner(row,nodeId));
  rows.value=value.data;page.value=target;pages.value=value.meta.pager?.total_pages??1;total.value=value.meta.pager?.total_items??0;historyState.value="ready";
 }catch(cause){if(stamp===version&&attempt===historyVersion){historyError.value=failure(cause);historyState.value="error";}}
}
watch(()=>[props.open,props.node?.id] as const,([open])=>{
 version++;latestVersion++;historyVersion++;
 latest.value=null;selected.value=null;rows.value=[];latestError.value=historyError.value="";page.value=pages.value=1;total.value=0;
 if(open&&props.node){void loadLatest();void loadHistory();}
},{immediate:true});
onUnmounted(()=>{version++;latestVersion++;historyVersion++;});
</script>

<template>
 <Modal :model-value="open" :title="`Node capabilities · ${node?.label??''}`" wide @update:model-value="value=>{if(!value)emit('close');}">
  <p class="hint-box">These are authenticated reports from the node. Version and reference matches do not prove installation, connectivity or enforcement. Runtime installation acknowledgements are tracked separately.</p>
  <section aria-label="Latest capability report">
   <div class="toolbar"><h3>Latest report</h3><button class="btn secondary" :disabled="latestState==='loading'" @click="loadLatest">Refresh latest report</button></div>
   <p v-if="latestState==='loading'">Loading latest report…</p>
   <p v-if="latestState==='error'" class="message error" role="alert">{{latestError}}</p>
   <template v-if="latestState==='ready'&&latest">
    <p v-if="latest.status==='absent'">No capability report has been received for this node.</p>
    <p v-else role="status">Latest report: {{latest.status==='fresh'?'Fresh':latest.status==='stale'?'Stale':'Future timestamp'}} · received {{faDate(latest.observation?.received_at??null)}}</p>
    <button v-if="latest.observation" class="btn secondary" @click="selected=latest.observation">View latest details</button>
   </template>
  </section>
  <section v-if="selected" aria-label="Selected capability details">
   <h3>{{selectedIsLatest?'Latest':'Historical'}} report #{{selected.observation_id}}</h3>
   <p>Observed {{faDate(selected.observed_at)}} · received {{faDate(selected.received_at)}}</p>
   <p class="mono report-digest">{{selected.report_sha256}}</p>
   <details v-for="adapter in selected.report.adapters" :key="adapter.kind" class="adapter-card" :open="adapter.kind==='xray'">
    <summary>{{adapterNames[adapter.kind]}} · {{adapter.executable.available?`Version ${adapter.executable.version}`:'No executable observation'}}</summary>
    <p>Adapter revision {{adapter.adapter_revision}}</p>
    <p v-if="adapter.executable.available">Reported binary version: {{adapter.executable.version}}</p><p v-else>Executable observation unavailable.</p>
    <p v-if="adapter.executable.sha256" class="mono report-digest">Binary SHA256: {{adapter.executable.sha256}}</p>
    <p v-if="adapter.kind==='sing_box'">V2Ray API build tag: {{adapter.executable.v2ray_api_build_tag?'Reported present':'Not reported'}}</p>
    <dl class="capability-list"><template v-for="operation in operations" :key="operation.key"><dt>{{operation.label}}</dt><dd><span>{{adapter[operation.key].implemented?'Implemented adapter':'No implementation'}}</span> · {{compatibility(adapter[operation.key])}}</dd></template></dl>
   </details>
  </section>
  <section aria-label="Capability report history">
   <div class="toolbar"><h3>Report history</h3><button class="btn secondary" :disabled="historyState==='loading'" @click="loadHistory()">Refresh history</button></div>
   <p v-if="historyState==='loading'">Loading report history…</p><p v-if="historyState==='error'" class="message error" role="alert">{{historyError}}</p>
   <p v-if="historyState==='ready'&&!rows.length">No reports on this page.</p>
   <button v-for="row in rows" :key="row.observation_id" class="btn secondary history-row" :aria-pressed="selected?.observation_id===row.observation_id" @click="selected=row">Report #{{row.observation_id}} · {{faDate(row.observed_at)}}</button>
   <div class="pager"><button :disabled="page<=1||historyState==='loading'" @click="loadHistory(page-1)">Previous reports</button><span>Page {{page}} · {{total}} reports</span><button :disabled="page>=pages||historyState==='loading'" @click="loadHistory(page+1)">Next reports</button></div>
  </section>
 </Modal>
</template>
<style scoped>
.adapter-card summary{cursor:pointer;font-weight:600}.adapter-card{border:1px solid var(--border);border-radius:12px;padding:14px;margin-block:12px}.report-digest{overflow-wrap:anywhere}.capability-list{display:grid;grid-template-columns:minmax(120px,1fr) minmax(0,2fr);gap:8px}.capability-list dd{margin:0}.history-row{display:block;margin-block:8px}@media(max-width:560px){.capability-list{grid-template-columns:1fr;gap:4px}.capability-list dd{margin-block-end:8px}}
</style>
