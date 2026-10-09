import type { SmsParserRequest, SmsParserReply } from "./smsParser.worker";
import { toRaw } from "vue";
export function createSmsParserClient(){
 let worker:Worker|null=null,sequence=0;
 const pending=new Map<number,{resolve:(value:SmsParserReply)=>void;reject:(cause:Error)=>void}>();
 function close():void{worker?.terminate();worker=null;pending.forEach(task=>task.reject(new Error("Parser editor closed.")));pending.clear();}
 function compute(request:Omit<SmsParserRequest,"id">):Promise<SmsParserReply>{
  if(!worker){worker=new Worker(new URL("./smsParser.worker.ts",import.meta.url),{type:"module"});worker.onmessage=({data}:MessageEvent<SmsParserReply>)=>{const task=pending.get(data.id);pending.delete(data.id);task?.resolve(data);};worker.onerror=()=>{close();};}
  const id=++sequence;const result=new Promise<SmsParserReply>((resolve,reject)=>pending.set(id,{resolve,reject}));
  try{worker.postMessage({...request,id,capabilities:toRaw(request.capabilities),value:toRaw(request.value),edit:toRaw(request.edit)});}catch(cause){pending.delete(id);throw cause;}
  return result;
 }
 return {compute,close};
}
