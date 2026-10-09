import type { SmsOriginCapabilities, SmsParserDefinition } from "@papilio/api";
export interface SmsParserEdit { field:keyof SmsParserDefinition; operation:"set"|"add"|"remove"; index?:number; member?:string; value?:unknown }
export interface SmsParserRequest { id:number; text?:string; value?:unknown; edit?:SmsParserEdit; capabilities:SmsOriginCapabilities }
export interface SmsParserReply { id:number; value:SmsParserDefinition|null; text:string|null; valid:boolean; error:string|null }
const literals=["credit_markers","debit_markers","clause_separators","reference_labels","rial_labels","toman_labels","grouping_separators"] as const;
const relations=["deposit_relations","balance_relations"] as const;
function structure(value:unknown,capabilities:SmsOriginCapabilities):value is SmsParserDefinition {
 if(!value||typeof value!=="object"||Array.isArray(value))return false;
 const data=value as Record<string,unknown>;
 return capabilities.parser_modes.includes(data.mode as SmsParserDefinition["mode"])&&typeof data.case_sensitive==="boolean"&&literals.every(key=>Array.isArray(data[key])&&(data[key] as unknown[]).every(entry=>typeof entry==="string"))&&relations.every(key=>Array.isArray(data[key])&&(data[key] as unknown[]).every(entry=>{if(!entry||typeof entry!=="object"||Array.isArray(entry))return false;const rule=entry as Record<string,unknown>;return typeof rule.marker==="string"&&capabilities.amount_relations.includes(rule.relation as never)&&(rule.implicit_unit===undefined||rule.implicit_unit===null||capabilities.units.includes(rule.implicit_unit as never));}));
}
function edit(value:SmsParserDefinition,change:SmsParserEdit):void {
 const data=value as unknown as Record<string,unknown>;
 if(change.index===undefined){if(change.operation==="set")data[change.field]=change.value;else if(change.operation==="add"&&Array.isArray(data[change.field]))(data[change.field] as unknown[]).push(change.value);return;}
 const list=data[change.field];if(!Array.isArray(list))return;
 if(change.operation==="remove")list.splice(change.index,1);
 else if(change.member){const row=list[change.index];if(row&&typeof row==="object")(row as Record<string,unknown>)[change.member]=change.value;}
 else list[change.index]=change.value;
}
self.onmessage=({data:request}:MessageEvent<SmsParserRequest>)=>{
 const reply:SmsParserReply={id:request.id,value:null,text:null,valid:false,error:null};
 try{
  const value:unknown=request.text!==undefined?JSON.parse(request.text):request.value;
  if(!structure(value,request.capabilities))throw new Error("The definition JSON cannot be displayed as literal rules. Correct its arrays in the advanced editor.");
  relations.forEach(key=>value[key].forEach(rule=>{if(rule.implicit_unit===undefined)rule.implicit_unit=null;}));
  if(request.edit)edit(value,request.edit);
  if(!structure(value,request.capabilities))throw new Error("The definition JSON cannot be displayed as literal rules. Correct its arrays in the advanced editor.");
  const text=JSON.stringify(value,null,2);reply.value=value;reply.text=text;
  const capacity=request.capabilities.capacity;
  const projection={mode:value.mode,credit_markers:value.credit_markers,debit_markers:value.debit_markers,clause_separators:value.clause_separators,deposit_relations:value.deposit_relations.map(rule=>({marker:rule.marker,relation:rule.relation,implicit_unit:rule.implicit_unit})),balance_relations:value.balance_relations.map(rule=>({marker:rule.marker,relation:rule.relation,implicit_unit:rule.implicit_unit})),reference_labels:value.reference_labels,rial_labels:value.rial_labels,toman_labels:value.toman_labels,grouping_separators:value.grouping_separators,case_sensitive:value.case_sensitive};
  if(capacity&&new TextEncoder().encode(JSON.stringify(projection)).length>capacity.max_profile_bytes)throw new Error("The definition exceeds the configured byte capacity.");
  if(capacity&&[...literals,...relations].some(key=>value[key].length>capacity.max_rules_per_field))throw new Error("The rule count exceeds the configured capacity.");
  const markers=[...literals.flatMap(key=>value[key]),...relations.flatMap(key=>value[key].map(rule=>rule.marker))];
  if(markers.some(marker=>marker.length===0))throw new Error("Fill each literal marker or remove the empty rule.");
  if(capacity&&markers.some(marker=>Array.from(marker).length>capacity.max_marker_chars))throw new Error("A literal marker exceeds the configured length.");
  reply.valid=true;
 }catch(cause){reply.error=cause instanceof Error?cause.message:"The parser definition could not be read.";}
 self.postMessage(reply);
};
