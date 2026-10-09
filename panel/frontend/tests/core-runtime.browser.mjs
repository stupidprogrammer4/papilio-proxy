// Interaction acceptance uses controlled HTTP; native runtime acceptance is separate.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage({timezoneId:"Asia/Tehran"}),errors=[],writes=[],reads=[];
const core={id:41,node_id:31,code:'owned',label:'Owned Xray',kind:'xray',supported_protocols:['vless_reality'],application_status:'applied',runtime:{revision:3,desired_revision_id:89,applied_revision_id:88,validated_revision_id:88,observed_status:'stopped',automation_paused:true,last_observed_at:'2026-10-07T00:00:00Z'}};
let epoch='controlled-epoch-41';
let usage={mode:'observe',configured_port:10085,available:true,reason_code:null,protected_ports:[10085,10086]};
let revision=3,fail=true,conflict=true,created=false,observeFail=true,allowStart=false,startBlockedReason;
const state=()=>({observed_process_epoch:epoch,usage,id:7,core_id:41,revision,desired_revision_id:created?99:null,applied_revision_id:null,validated_revision_id:null,observed_status:'stopped',automation_paused:true,last_observed_at:'2026-10-07T00:00:00Z',enabled:true,allow_start:allowStart,start_blocked_reason:startBlockedReason,allowed_actions:['validate','stop','reconcile']});
const version=id=>({id,core_id:41,created_by_staff_id:5,usage_sha256:id===92?null:'c'.repeat(64),membership_sha256:id===92?null:'b'.repeat(64),mode:'isolated',bundle_sha256:'a'.repeat(64),artifact_count:2,created_at:'2026-10-07T00:00:00Z'});
const respond=(r,data,status=200)=>r.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
page.on('pageerror',e=>errors.push(e.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),url=new URL(request.url()),path=url.pathname.slice(4);
 if(path==='/v1/admin/auth/me')return respond(route,{username:'fixture',scopes:['*'],csrf_token:'fixture-csrf'});
 if(path==='/v1/admin/preferences')return respond(route,{data:{revision:0,values:{brand_title:'Papilio'}}});
 if(path==='/v1/admin/network/nodes/31')return respond(route,{data:{id:31,label:'Owned node',code:'owned'}});
 if(path==='/v1/admin/network/nodes/31/cores')return respond(route,{data:[core],meta:{pager:{total_pages:1}}});
 const base='/v1/admin/network/cores/41/runtime';
 if(path===base)return respond(route,{data:state()});
 if(path===base+'/revisions'&&request.method()==='GET'){
  const page=Number(url.searchParams.get('page'));reads.push(page);
  return respond(route,{data:[version(page===2?92:91)],meta:{pager:{total_pages:2}}});
 }
 if(path===base+'/revisions'){
  assert.deepEqual(request.postDataJSON(),{expected_revision:4,mode:'isolated'});created=true;revision++;
  return respond(route,{data:version(99)});
 }
 if(path===base+'/commands'&&request.method()==='GET')return respond(route,{data:created?[{id:111,core_id:41,node_id:31,purpose:'provisioning',created_by_staff_id:null,reconcile_mode:null,action:'validate',revision_id:99,state:'failed',request_key:'fixture',reason:'Checked runtime',error_code:'validation_failed',claim_until:null,created_at:'2026-10-07T00:00:00Z'}]:[],meta:{pager:{total_pages:1}}});
 if(path===base+'/commands'){
  const data=request.postDataJSON();writes.push(data);
  if(data.action==='reconcile'&&observeFail){observeFail=false;return respond(route,{error:{message_code:'request_failed'}},503);}
  if(fail){fail=false;return respond(route,{error:{message_code:'request_failed'}},503);}
  if(conflict){conflict=false;revision=4;return respond(route,{error:{message_code:'runtime_revision_conflict'}},409);}
  revision++;return respond(route,{data:{id:110,core_id:41,node_id:31,purpose:'operator',created_by_staff_id:5,...data,state:'queued',error_code:null,claim_until:null,created_at:'2026-10-07T00:00:00Z'}});
 }
 return respond(route,{data:[],meta:{pager:{total_pages:1}}});
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/network/31/cores');
 await page.getByText('Applied #88 · desired #89',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Runtime control',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Runtime · Owned Xray'});await dialog.getByText('Immutable revisions',{exact:true}).waitFor();
 const capability=dialog.locator('section[aria-label="Usage configuration capability"]');
 assert.match(await dialog.innerText(),/Last reported process epoch: controlled-epoch-41/);
 assert.match(await capability.innerText(),/Configured mode: Observe counters/);
 assert.match(await capability.innerText(),/Configuration capability: Available/);
 assert.match(await capability.innerText(),/Configured local stats port: 10085/);
 assert.match(await capability.innerText(),/10085, 10086/);
 assert.match(await capability.innerText(),/not measured usage, installed enforcement or current connectivity/);
 assert.equal(await dialog.getByLabel('Captured usage configuration SHA-256').inputValue(),'c'.repeat(64));
 usage={mode:'polled_stop',configured_port:10085,available:false,reason_code:'runtime_usage_port_conflict',protected_ports:[10085,10086]};
 await dialog.getByRole('button',{name:'Refresh runtime and history'}).click();await capability.getByText('Unavailable',{exact:true}).waitFor();
 assert.match(await capability.innerText(),/Poll counters and stop/);assert.match(await capability.innerText(),/runtime_usage_port_conflict/);
 usage={mode:'disabled',configured_port:null,available:false,reason_code:'runtime_usage_disabled',protected_ports:[]};
 await dialog.getByRole('button',{name:'Refresh runtime and history'}).click();await capability.getByText('Usage collection is disabled in application settings.',{exact:true}).waitFor();
 assert.match(await capability.innerText(),/Not configured/);assert.match(await capability.innerText(),/None reported/);
 usage=undefined;
 await dialog.getByRole('button',{name:'Refresh runtime and history'}).click();await capability.getByText('Usage configuration capability is unavailable right now.',{exact:true}).waitFor();
 epoch=null;
 await dialog.getByRole('button',{name:'Refresh runtime and history'}).click();await dialog.getByText('Not reported',{exact:true}).waitFor();
 assert.equal(writes.length,0);
 assert.deepEqual(await dialog.getByLabel('Runtime action').locator('option').allTextContents(),['Validate','Stop','Reconcile']);
 await dialog.getByRole('button',{name:'Select revision',exact:true}).click();
 await dialog.getByRole('button',{name:'Next revisions'}).click();await dialog.getByRole('heading',{name:'Revision #92 · isolated'}).waitFor();
 assert.match(await dialog.innerText(),/Selected revision: #91/);
 assert.match(await dialog.innerText(),/No captured profile provenance/);
 assert.match(await dialog.innerText(),/No captured usage configuration provenance/);
 await dialog.getByLabel('Command reason').fill('Checked runtime');
 await dialog.getByRole('button',{name:'Queue command',exact:true}).click();await dialog.getByRole('alert').waitFor();
 assert.equal(await dialog.getByLabel('Command reason').inputValue(),'Checked runtime');
 await dialog.getByRole('button',{name:'Queue command',exact:true}).click();await dialog.getByRole('button',{name:'Use current control revision'}).waitFor();
 assert.deepEqual(writes[0],writes[1]);assert.equal(writes[0].revision_id,91);
 await dialog.getByRole('button',{name:'Use current control revision'}).click();
 await dialog.getByRole('button',{name:'Capture immutable revision'}).click();await dialog.getByText('Immutable revision captured. No core was started.').waitFor();
 assert.equal(await dialog.getByLabel('Captured profile membership SHA-256').inputValue(),'b'.repeat(64));
 assert.match(await dialog.innerText(),/Selected revision: #99/);
 await dialog.getByRole('button',{name:'Queue command',exact:true}).click();await dialog.getByText(/Command #110 recorded/).waitFor();
 assert.equal(writes[2].expected_revision,5);assert.equal(writes[2].revision_id,99);assert.notEqual(writes[2].request_key,writes[0].request_key);
 assert.match(await dialog.innerText(),/Node error: validation_failed/);
 assert.match(await dialog.innerText(),/Paused for this core/);assert.match(await dialog.innerText(),/Last observation: 7 Oct 2026, 03:30/);assert.match(await dialog.innerText(),/Automatic provisioning/);assert.match(await dialog.innerText(),/command acknowledgement, not a live health check/);
 assert.match(await dialog.innerText(),/Staff #5/);assert.match(await dialog.innerText(),/System/);
 await dialog.getByLabel('Runtime action').selectOption('reconcile');
 assert.equal(await dialog.getByLabel('Reconciliation mode').inputValue(),'observe');
 assert.equal(await dialog.getByLabel('Reconciliation mode').locator('option[value="restore"]').evaluate(option => option.disabled),true);
 await dialog.getByRole('button',{name:'Queue command',exact:true}).click();await dialog.getByRole('alert').waitFor();
 assert.equal(await dialog.getByLabel('Reconciliation mode').inputValue(),'observe');
 await dialog.getByRole('button',{name:'Queue command',exact:true}).click();await dialog.getByText(/Command #110 recorded/).waitFor();
 assert.deepEqual(writes[3],writes[4]);assert.equal(writes[3].reconcile_mode,'observe');assert.equal(writes[3].revision_id,null);
 assert.equal(writes[2].reconcile_mode,null);
 await page.setViewportSize({width:390,height:844});assert(await dialog.evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}));
 await dialog.getByRole('button',{name:'Close dialog'}).click();await dialog.waitFor({state:'hidden'});
 await page.getByRole('button',{name:'Runtime control',exact:true}).click();await dialog.getByText('Immutable revisions',{exact:true}).waitFor();
 assert.equal(await dialog.getByLabel('Command reason').inputValue(),'');assert.match(await dialog.innerText(),/Select a revision below/);
 assert(reads.includes(2));assert.deepEqual(errors,[]);
 const beforeBlockedWrites=writes.length;
 allowStart=true;startBlockedReason=null;
 await dialog.getByRole('button',{name:'Refresh runtime and history'}).click();
 await dialog.getByRole('button',{name:'Select revision',exact:true}).click();
 await dialog.getByLabel('Runtime action').selectOption('reconcile');
 await dialog.getByLabel('Reconciliation mode').selectOption('restore');
 await dialog.getByLabel('Command reason').fill('Controlled restoration');
 assert.equal(await dialog.getByRole('button',{name:'Queue command',exact:true}).isEnabled(),true);
 startBlockedReason='runtime_usage_unresolved_grants';
 await dialog.getByRole('button',{name:'Refresh runtime and history'}).click();
 await dialog.getByText('runtime_usage_unresolved_grants',{exact:true}).waitFor();
 assert.equal(await dialog.getByRole('button',{name:'Queue command',exact:true}).isDisabled(),true);
 assert.equal(await dialog.getByLabel('Reconciliation mode').locator('option[value="restore"]').evaluate(option=>option.disabled),true);
 assert.equal(await dialog.getByLabel('Command reason').inputValue(),'Controlled restoration');
 assert.equal(await dialog.getByRole('button',{name:'Capture immutable revision',exact:true}).isEnabled(),true);
 await dialog.getByLabel('Runtime action').selectOption('stop');
 assert.equal(await dialog.getByRole('button',{name:'Queue command',exact:true}).isEnabled(),true);
 await dialog.getByLabel('Runtime action').selectOption('reconcile');
 await dialog.getByLabel('Reconciliation mode').selectOption('observe');
 assert.equal(await dialog.getByRole('button',{name:'Queue command',exact:true}).isEnabled(),true);
 startBlockedReason=undefined;
 await dialog.getByRole('button',{name:'Refresh runtime and history'}).click();
 await dialog.getByText('runtime_usage_unresolved_grants',{exact:true}).waitFor({state:'hidden'});
 assert.equal(await dialog.getByLabel('Reconciliation mode').locator('option[value="restore"]').evaluate(option=>option.disabled),false);
 assert.equal(writes.length,beforeBlockedWrites);assert.deepEqual(errors,[]);
 console.log('Runtime identity, allowed actions, cross-page selection, network retry key retention, stale draft recovery, snapshot/command distinction, node errors, usage disabled/available/unavailable/legacy capability, two protected ports, provenance, reported/null epoch and mobile passed; controlled HTTP.');
}finally{await browser.close();}
