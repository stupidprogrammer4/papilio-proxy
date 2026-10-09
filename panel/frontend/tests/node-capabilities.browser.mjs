// Actual Vue with controlled HTTP; native observation and binary checks are separate.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const node=id=>({id,code:`node-${id}`,label:`Node ${id}`,public_host:'example.invalid',public_port:443,protocol:'vless_reality',is_enabled:false});
const scopes={validation:'local_immutable_document_validation',installation:'fresh_authorized_immutable_bundle_lifecycle',installed_membership:'live_exact_installed_membership_only',counters:'merged_xray_scoped_cumulative_counters',polled_stop:'whole_merged_core_stop_with_poll_overrun',strict_quota_expiry:'no_strict_quota_or_expiry_guarantee',ip_admission:'source_ip_not_device_identity',device_admission:'no_device_count_guarantee',final_counters:'unresolved_grants_preserved',protocol_matrix:'export_or_binary_version_is_not_protocol_acceptance'};
const keys=['validation','installation','installed_membership','counters','polled_stop','strict_quota_expiry','ip_admission','device_admission','final_counters','protocol_matrix'];
function observation(id,nodeId=31){
 const adapters=['xray','sing_box','openvpn','wireguard','hysteria'].map(kind=>{
  const installed=kind==='xray'||kind==='sing_box';
  return {kind,adapter_revision:1,executable:{available:installed,version:installed?'1.2.3':null,sha256:installed?'a'.repeat(64):null,v2ray_api_build_tag:false,reason_code:installed?null:'adapter_unavailable'},...Object.fromEntries(keys.map(key=>[key,{implemented:installed&&(['validation','installation','installed_membership'].includes(key)||kind==='xray'&&['counters','polled_stop'].includes(key)),compatibility:installed&&['validation','installation','installed_membership'].includes(key)?'reference_match':'unavailable',scope:scopes[key],reason_code:installed&&['validation','installation','installed_membership'].includes(key)?null:'adapter_unavailable'}]))};
 });
 return {observation_id:id,node_id:nodeId,node_code:`node-${nodeId}`,report_id:'b'.repeat(32),report_sha256:'c'.repeat(64),observed_at:'2026-10-08T00:00:00Z',received_at:'2026-10-08T00:01:00Z',evidence_kind:'authenticated_node_self_report',report:{schema_revision:1,observed_at:'2026-10-08T00:00:00Z',adapters}};
}
const respond=(route,body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
async function scenario(run){
 const context=await browser.newContext(),page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',cause=>errors.push(cause.message));
 const state={latest:{node_id:31,status:'absent',observation:null},historyFailure:false,extra:null};
 await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname.slice(4);
  requests.push({path,method:req.method()});
  if(state.extra&&await state.extra(route,path,req))return;
  if(path==='/v1/admin/auth/me')return respond(route,{username:'controlled',scopes:['network:read'],csrf_token:'controlled'});
  if(path==='/v1/admin/preferences')return respond(route,{data:{revision:0,values:{brand_title:'Controlled'}}});
  if(path==='/v1/admin/network/nodes')return respond(route,{data:[node(31),node(32)],meta:{pager:{total_pages:1,total_items:2}}});
  if(path.endsWith('/capabilities/latest'))return respond(route,{data:state.latest});
  if(path.endsWith('/capabilities/history')){
   if(state.historyFailure)return respond(route,{error:{message_code:'request_failed'}},503);
   const current=Number(url.searchParams.get('page'));
   return respond(route,{data:state.latest.status==='absent'?[]:[observation(current===2?13:12)],meta:{pager:{total_pages:2,total_items:2}}});
  }
  return respond(route,{data:[],meta:{pager:{total_pages:1}}});
 });
 try{await run(page,state);assert.deepEqual(errors,[]);assert.equal(requests.filter(row=>row.method!=='GET').length,0,'read-only metadata initiated a write');}
 finally{await context.close();}
}
async function open(page,id=31){
 await page.getByRole('row').filter({hasText:`Node ${id}`}).getByRole('button',{name:'Capabilities',exact:true}).click();
 return page.getByRole('dialog',{name:`Node capabilities · Node ${id}`,exact:true});
}
try{
 await scenario(async(page,state)=>{
  await page.goto(process.env.PANEL_ORIGIN+'/network');
  assert.equal(await page.getByRole('button',{name:'+ Register node',exact:true}).count(),0);
  const dialog=await open(page);
  await dialog.getByText('No capability report has been received for this node.',{exact:true}).waitFor();
  state.latest={node_id:31,status:'fresh',observation:observation(11)};
  await dialog.getByRole('button',{name:'Refresh latest report',exact:true}).click();
  await dialog.getByRole('heading',{name:'Latest report #11',exact:true}).waitFor();
  assert.equal(await dialog.getByText('Reported reference match',{exact:false}).count()>0,true);
  await dialog.getByRole('button',{name:'Refresh history',exact:true}).click();
  await dialog.getByRole('button',{name:/^Report #12/}).click();
  await dialog.getByRole('heading',{name:'Historical report #12',exact:true}).waitFor();
  await dialog.getByRole('button',{name:'Next reports',exact:true}).click();
  await dialog.getByRole('button',{name:/^Report #13/}).waitFor();
  assert.equal(await dialog.getByRole('heading',{name:'Historical report #12',exact:true}).count(),1,'paging discarded the selected report');
  state.latest={...state.latest,status:'stale'};
  await dialog.getByRole('button',{name:'Refresh latest report',exact:true}).click();
  await dialog.getByText('Latest report: Stale',{exact:false}).waitFor();
  assert.equal(await dialog.getByRole('heading',{name:'Historical report #12',exact:true}).count(),1);
  state.latest={...state.latest,status:'future'};
  await dialog.getByRole('button',{name:'Refresh latest report',exact:true}).click();
  await dialog.getByText('Latest report: Future timestamp',{exact:false}).waitFor();
  state.historyFailure=true;
  await dialog.getByRole('button',{name:'Refresh history',exact:true}).click();
  await dialog.getByRole('alert').waitFor();
  assert.equal(await dialog.getByText('No reports on this page.',{exact:true}).count(),0,'failed history was labelled empty');
  state.historyFailure=false;
  await dialog.getByRole('button',{name:'Refresh history',exact:true}).click();
  await dialog.getByRole('button',{name:/^Report #13/}).waitFor();
  await page.setViewportSize({width:390,height:844});
  assert.equal(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1),true,'mobile modal overflow');
  state.latest={node_id:31,status:'fresh',observation:null};
  await dialog.getByRole('button',{name:'Refresh latest report',exact:true}).click();
  await dialog.getByRole('alert').waitFor();
  assert.equal(await dialog.getByRole('heading',{name:'Historical report #12',exact:true}).count(),1);
  await dialog.locator('.modal-body').evaluate(el=>{el.scrollTop=0;});
  if(process.env.CAPABILITIES_SCREENSHOT)await page.screenshot({path:process.env.CAPABILITIES_SCREENSHOT});
 });
 await scenario(async(page,state)=>{
  let release,started;
  const held=new Promise(resolve=>{release=resolve;}),begun=new Promise(resolve=>{started=resolve;});
  state.extra=async(route,path)=>{
   if(path==='/v1/admin/network/nodes/31/capabilities/latest'){
    started();await held;await respond(route,{data:{node_id:31,status:'fresh',observation:observation(101)}});return true;
   }
   if(path==='/v1/admin/network/nodes/32/capabilities/latest'){
    await respond(route,{data:{node_id:32,status:'fresh',observation:observation(202,32)}});return true;
   }
   if(path==='/v1/admin/network/nodes/32/capabilities/history'){
    await respond(route,{data:[],meta:{pager:{total_pages:1,total_items:0}}});return true;
   }
   return false;
  };
  await page.goto(process.env.PANEL_ORIGIN+'/network');
  const first=await open(page);await begun;
  await first.getByRole('button',{name:'Close dialog',exact:true}).click();
  const second=await open(page,32);
  await second.getByRole('heading',{name:'Latest report #202',exact:true}).waitFor();
  const response=page.waitForResponse(value=>value.url().endsWith('/nodes/31/capabilities/latest'));
  release();await response;
  assert.equal(await second.getByRole('heading',{name:'Latest report #202',exact:true}).count(),1);
  assert.equal(await second.getByRole('heading',{name:'Latest report #101',exact:true}).count(),0);
 });
 console.log('Node capability consumer passed: read scopes, absent/fresh/stale, retained history paging, failure/retry, node response fencing, mobile; controlled HTTP.');
}finally{await browser.close();}
