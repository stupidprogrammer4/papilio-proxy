// Actual Vue browser; HTTP contracts are controlled fixtures, not live provisioning evidence.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const modulePath=process.env.PLAYWRIGHT_MODULE,origin=process.env.PANEL_ORIGIN;
if(!modulePath||!origin)throw Error('Set PLAYWRIGHT_MODULE and PANEL_ORIGIN');
const {chromium}=await import(pathToFileURL(modulePath).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],planWrites=[];
let scopes=['*'],configAttempts=0,planAttempts=0,healthChecks=0;
const list=data=>({data,meta:{pager:{total_items:data.length,total_pages:1}}});
const respond=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
const node={id:31,code:'fixture-node',label:'Fixture node',public_host:'fixture.invalid',public_port:443,protocol:'vless_reality',is_enabled:true};
const core={id:41,node_id:31,code:'fixture-core',label:'Fixture Xray',kind:'xray',supported_protocols:['vless_reality'],application_status:'draft'};
const config={id:91,node_id:31,core_id:41,label:'Fixture configuration',protocol:'vless_reality',listen_port:443,port_network:'tcp',revision:1,application_status:'draft',options:{protocol:'vless_reality',listen_address:'0.0.0.0',server_name:'fixture.invalid',target_port:443}};
const plan={id:21,code:'fixture-plan',title:'Fixture plan',quota_bytes:1073741824,duration_days:30,price_rial:10000,sort_order:0,is_active:true,group_id:null,quota_policy:null,fulfillment:null,ip_limit:null};
page.on('pageerror',error=>errors.push(error.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const req=route.request(),path=new URL(req.url()).pathname.slice(4),method=req.method();
 if(path==='/v1/admin/auth/me')return respond(route,{username:'browser-fixture',scopes,csrf_token:'controlled-browser-token'});
 if(path==='/v1/admin/network/configurations'&&method==='POST'){
  const body=req.postDataJSON();assert.equal(body.core_id,41);assert.equal(body.node_id,31);assert.equal(body.options.protocol,'vless_reality');assert.equal(body.label,'Retained configuration');
  if(++configAttempts===1)return respond(route,{error:{message_code:'request_failed'}},409);
  return respond(route,{data:{...config,id:92,label:body.label,options:body.options}});
 }
 if(path==='/v1/admin/network/health/31/check'){assert.equal(method,'POST');healthChecks++;return respond(route,{data:{node_id:31,status:'stale',checked_at:new Date().toISOString()}});}
 if(path==='/v1/admin/network/health')return respond(route,list([{node_id:31,code:node.code,label:node.label,protocol:node.protocol,is_enabled:true,status:'stale',sample_count:2,successful_count:1,average_latency_ms:30,last_sample_at:'2026-01-01T00:00:00Z',checked_at:'2026-01-01T00:00:00Z'}]));
 if(path==='/v1/admin/network/quality')return respond(route,{data:[{node_id:31,code:node.code,label:node.label,protocol:node.protocol,client_network:'Fixture mobile',sample_count:1,successful_count:1,average_latency_ms:30,score:null}]});
 if(path==='/v1/admin/network/configurations'&&method==='GET')return respond(route,list(new URL(req.url()).searchParams.get('node_id')==='31'?[config]:[]));
 if(path==='/v1/admin/network/configurations/91')return respond(route,{data:config});
 if(path==='/v1/admin/network/configurations/92')return respond(route,{data:{...config,id:92,label:'Retained configuration'}});
 if(path==='/v1/admin/network/nodes/31')return respond(route,{data:node});
 if(path==='/v1/admin/network/nodes/32')return respond(route,{data:{...node,id:32,label:'Other fixture node'}});
 if(path==='/v1/admin/network/cores/41')return respond(route,{data:core});
 if(path==='/v1/admin/network/nodes/31/cores')return respond(route,list([core]));
 if(path==='/v1/admin/network/nodes')return respond(route,list([node]));
 if(path==='/v1/admin/plans/policy-defaults')return respond(route,{data:{quota_policy:{},fulfillment:{},ip_limit:{}}});
 if(path==='/v1/admin/plans'&&method==='POST'){
  const body=req.postDataJSON();if(++planAttempts===1)return respond(route,{error:{message_code:'request_failed'}},409);
  planWrites.push(body);return respond(route,{data:{...plan,...body,is_active:false}});
 }
 if(path==='/v1/admin/plans')return respond(route,list([plan]));
 if(path==='/v1/admin/plans/21/configurations')return respond(route,list([{node_id:31,node_label:node.label,configuration_id:91,label:config.label,protocol:config.protocol,host_id:61,group_id:71,is_enabled:true}]));
 return respond(route,list([]));
});
try{
 await page.goto(origin+'/configurations?configuration_id=91');await page.getByRole('button',{name:'Edit settings',exact:true}).waitFor();
 await page.getByRole('button',{name:'Full server JSON and history',exact:true}).waitFor();await page.getByRole('button',{name:'View and edit JSON',exact:true}).waitFor();
 await page.evaluate(async()=>{await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/network/32/configurations?configuration_id=91');});
 await page.getByRole('alert').filter({hasText:'belongs to a different node'}).waitFor();assert.equal(await page.getByRole('button',{name:'Edit settings',exact:true}).count(),0);
 assert.equal(await page.getByRole('button',{name:'Full server JSON and history',exact:true}).count(),0);
 await page.goto(origin+'/network/31/configurations');await page.getByRole('button',{name:'+ Create configuration',exact:true}).click();
 const configDialog=page.getByRole('dialog',{name:'Create configuration',exact:true});
 await configDialog.getByRole('button',{name:'Fixture Xray · xray',exact:true}).click();await configDialog.getByLabel('Label',{exact:true}).fill('Retained configuration');await configDialog.getByLabel('Node listen address').fill('0.0.0.0');await configDialog.getByLabel('TLS / REALITY server name').fill('fixture.invalid');await configDialog.getByLabel('REALITY target port').fill('443');
 await configDialog.getByRole('button',{name:'Create draft',exact:true}).click();await configDialog.getByRole('alert').waitFor();assert.equal(await configDialog.getByLabel('Label',{exact:true}).inputValue(),'Retained configuration');
 await configDialog.getByRole('button',{name:'Create draft',exact:true}).click();await configDialog.waitFor({state:'hidden'});assert.equal(configAttempts,2);
 await page.goto(origin+'/plans');
 for(const [mode,quota,duration] of [['quota_timed',2,30],['quota_only',3,null],['time_only',null,60]]){
  await page.getByRole('button',{name:'+ Create plan',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Create plan',exact:true});
  await dialog.getByLabel('Unique code',{exact:true}).fill('fixture-'+mode);await dialog.getByLabel('Display name').fill('Fixture '+mode);await dialog.getByLabel('Plan type',{exact:true}).selectOption(mode);
  assert.equal(await dialog.getByLabel('Data quota (GiB)',{exact:true}).count(),quota===null?0:1);assert.equal(await dialog.getByLabel('Duration (days)',{exact:true}).count(),duration===null?0:1);
  if(quota!==null)await dialog.getByLabel('Data quota (GiB)',{exact:true}).fill(String(quota));if(duration!==null)await dialog.getByLabel('Duration (days)',{exact:true}).fill(String(duration));await dialog.getByLabel('Price (toman)',{exact:true}).fill('100');await dialog.getByLabel('Display order',{exact:true}).fill('0');await dialog.getByRole('button',{name:'Create plan',exact:true}).click();
  if(mode==='quota_timed'){await dialog.getByRole('alert').waitFor();assert.equal(await dialog.getByLabel('Display name').inputValue(),'Fixture '+mode);await dialog.getByRole('button',{name:'Create plan',exact:true}).click();}
  await dialog.waitFor({state:'hidden'});const body=planWrites.at(-1);assert.equal(body.quota_bytes,quota===null?null:quota*1073741824);assert.equal(body.duration_days,duration);assert.equal(body.price_rial,1000);
 }
 await page.goto(origin+'/connection-lab');await page.getByRole('button',{name:'Fixture node Enabled',exact:true}).click();await page.getByText('Stale observations',{exact:true}).waitFor();await page.getByRole('button',{name:'Fixture Xray · xray',exact:true}).click();await page.getByRole('button',{name:'Fixture configuration · vless_reality · 443',exact:true}).click();
 await page.getByRole('button',{name:'Recalculate recorded health',exact:true}).click();await page.getByRole('status').filter({hasText:'No network probe was started'}).waitFor();assert.equal(healthChecks,1);
 await page.getByLabel('Measurement source network',{exact:true}).fill('Fixture mobile');await page.getByRole('button',{name:'Compare recorded observations',exact:true}).click();await page.getByText('Insufficient eligible data',{exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:/run.*(benchmark|speed)/i}).count(),0);await page.getByRole('link',{name:'Open selected configuration tools',exact:true}).click();await page.getByRole('button',{name:'Edit settings',exact:true}).waitFor();assert(new URL(page.url()).searchParams.get('configuration_id')==='91');
 scopes=['catalog:read'];await page.goto(origin+'/plans');await page.getByRole('button',{name:'Details',exact:true}).click();const detail=page.getByRole('dialog',{name:'Fixture plan',exact:true});await detail.getByText('Fixture configuration',{exact:true}).waitFor();assert.equal(await detail.getByRole('button',{name:'Edit this plan',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'+ Create plan',exact:true}).count(),0);
 assert.deepEqual(errors,[]);console.log('PASS: exact configuration deep link/SPA parent boundary; both JSON editors accessible; selected core create payload/failure draft; all three plan contracts; read-only bundle details; connection lab recorded health/recalculation/quality/config context');
}finally{await page.close();await browser.close();}
