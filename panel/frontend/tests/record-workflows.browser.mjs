import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const modulePath=process.env.PLAYWRIGHT_MODULE,origin=process.env.PANEL_ORIGIN;
if(!modulePath||!origin)throw Error('Set PLAYWRIGHT_MODULE and PANEL_ORIGIN');
const {chromium}=await import(pathToFileURL(modulePath).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],requests=[];
const list=data=>({data,meta:{pager:{total_items:data.length,total_pages:1,has_prev:false,has_next:false}}});
const response=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
const access={is_active:true,services_enabled:true,renewals_enabled:true};
const role={id:11,code:'fixture-role',title:'Fixture role',is_active:true,revision:1,scopes:[]};
const destination={destination_id:51,title:'Fixture receiving account',kind:'card',account:'6037990000000001',recipient:'Fixture recipient',bank_name:'Fixture bank',instructions:null,is_active:true};
const expiry=new Date(Date.now()+86_400_000).toISOString();
let devices=[{id:71,label:'Fixture phone',senders:['FixtureBank'],is_active:true,revision:1,expires_at:expiry,approval_mode:'manual',destination_id:51}];
let roleAttempts=0,enrollAttempts=0,editAttempts=0,visibleKey='';
const subscription={id:999,customer_id:101,plan_id:1,quota_bytes:1024,used_bytes:0,price_rial:1000,duration_days:30,expires_at:expiry,status:'active',auto_renew:false,renewal_count:0,failure_reason:null,group_id:null,entitlement_kind:'paid',activated_at:expiry};
page.on('pageerror',error=>errors.push(error.message));
await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
 const req=route.request(),url=new URL(req.url()),path=url.pathname.slice(4),method=req.method();requests.push({path,method});
 if(path==='/v1/admin/auth/me')return response(route,{username:'browser-fixture',scopes:['*'],csrf_token:'controlled-browser-token'});
 if(path==='/v1/admin/branding')return response(route,{data:{brand_title:'Browser fixture'}});
 if(path==='/v1/admin/staff/scope-catalog')return response(route,{data:{areas:['staff','payments','subscriptions'],levels:['read','create','update','manage']}});
 if(path==='/v1/admin/roles'&&method==='POST'){roleAttempts++;if(roleAttempts===1)return response(route,{error:{message_code:'request_failed'}},409);return response(route,{data:{...role,...req.postDataJSON()}});}
 if(path==='/v1/admin/roles')return response(route,list([role]));
 if(path==='/v1/admin/payments/topups')return response(route,list(url.searchParams.get('status')==='approved'?[{id:88,customer_id:101,amount_rial:1000,status:'approved',bank_reference:'fixture-credit',approved_by_staff_id:null,approved_by_device_id:71,approved_by_sms_id:78}]:[]));
 if(path==='/v1/admin/payments/sms')return response(route,list([{id:78,device_id:71,event_id:'fixture-sms',sender:'FixtureBank',amount_rial:1000,bank_reference:'fixture-credit',sent_at:expiry}]));
 if(path==='/v1/admin/payments/destinations')return response(route,list([destination]));
 if(path==='/v1/admin/payments/sms-devices'&&method==='POST'){
  enrollAttempts++;if(enrollAttempts===1)return response(route,{error:{message_code:'sms_device_sender_capacity'}},409);
  const data=req.postDataJSON();assert.equal(data.destination_id,51);assert.equal(data.approval_mode,'unique_sms');assert(new Date(data.expires_at).getTime()>Date.now());
  const device={...data,id:72,revision:1};devices.push(device);visibleKey=randomBytes(32).toString('hex');return response(route,{data:{device,api_key:visibleKey}});
 }
 if(path==='/v1/admin/payments/sms-devices')return response(route,list(devices.filter(device=>device.label.includes(url.searchParams.get('q')??''))));
 if(path==='/v1/admin/payments/sms-devices/71'&&method==='PUT'){
  editAttempts++;const data=req.postDataJSON(),device=devices.find(row=>row.id===71);if(editAttempts===1){device.revision=2;return response(route,{error:{message_code:'sms_device_revision_conflict'}},409);}assert.equal(data.expected_revision,2);assert.equal(data.label,'Retained revised phone');Object.assign(device,data,{revision:3});return response(route,{data:device});
 }
 if(path==='/v1/admin/payments/sms-devices/72/rotate'){
  assert.equal(req.postDataJSON().expected_revision,1);const device=devices.find(row=>row.id===72);device.revision++;visibleKey=randomBytes(32).toString('hex');return response(route,{data:{device,api_key:visibleKey}});
 }
 if(path==='/v1/admin/payments/sms-devices/72'&&method==='PUT'){
  const data=req.postDataJSON(),device=devices.find(row=>row.id===72);assert.equal(data.expected_revision,2);assert.equal(data.is_active,false);Object.assign(device,data,{revision:3});return response(route,{data:device});
 }
 if(path==='/v1/admin/subscriptions/999')return response(route,{data:subscription});
 if(path==='/v1/admin/subscriptions')return response(route,list([]));
 if(path.startsWith('/v1/admin/network/host-groups/'))return response(route,{data:{id:81,code:'fixture-group',title:'Fixture delivery group',is_enabled:true}});
 if(path==='/v1/admin/network/host-groups')return response(route,list([]));
 if(path.endsWith('/ip-policy'))return response(route,{data:{subscription_id:999,policy:null,defaults:{mode:'reject_new',max_ips:1,lease_seconds:60,ban_seconds:60,max_ips_ceiling:10,max_lease_seconds:3600,max_ban_seconds:3600}}});
 if(path.endsWith('/summary'))return response(route,{data:{upload_bytes:0,download_bytes:0,total_bytes:0,sample_count:0}});
 if(path.endsWith('/provisioning'))return response(route,list([]));
 return response(route,list([]));
});
try{
 await page.goto(origin+'/roles');await page.getByRole('button',{name:'+ Create role',exact:true}).click();
 const roleDialog=page.getByRole('dialog',{name:'Create role',exact:true});
 await roleDialog.getByLabel('Unique role code').fill('new-fixture-role');await roleDialog.getByLabel('Role name').fill('New fixture role');await roleDialog.getByLabel('Creation reason').fill('Browser workflow check');
 await roleDialog.getByRole('button',{name:'Create role',exact:true}).click();await roleDialog.getByRole('alert').waitFor();
 assert.equal(await roleDialog.getByLabel('Role name').inputValue(),'New fixture role');
 await roleDialog.getByRole('button',{name:'Create role',exact:true}).click();await roleDialog.waitFor({state:'hidden'});
 assert.equal(roleAttempts,2);
 await page.goto(origin+'/payments');await page.getByRole('combobox',{name:/^Request status/}).selectOption('approved');await page.getByRole('row',{name:/^88 101/}).click();
 const provenance=page.getByLabel('Payment approval provenance',{exact:true});await provenance.getByText('Enrolled SMS device 71',{exact:true}).waitFor();assert.equal(await provenance.getByText('78',{exact:true}).count(),1);
 await page.getByRole('button',{name:'+ Enroll device',exact:true}).click();
 const deviceDialog=page.getByRole('dialog',{name:'Enroll SMS device',exact:true});
 await deviceDialog.getByLabel('Device name').fill('Enrolled fixture phone');await deviceDialog.getByLabel('Allowed bank sender IDs (one per line)').fill('FixtureBank');
 await deviceDialog.getByLabel(/^Expiry \(/).fill(expiry.slice(0,16));await deviceDialog.getByLabel('Device enabled').check();await deviceDialog.getByLabel('Approval policy').selectOption('unique_sms');
 await deviceDialog.getByRole('button',{name:'Select',exact:true}).click();await deviceDialog.getByRole('button',{name:'Enroll and reveal key',exact:true}).click();
 await deviceDialog.getByRole('alert').waitFor();assert.equal(await deviceDialog.getByLabel('Device name').inputValue(),'Enrolled fixture phone');
 await deviceDialog.getByRole('button',{name:'Enroll and reveal key',exact:true}).click();await deviceDialog.waitFor({state:'hidden'});
 const keyDialog=page.getByRole('dialog',{name:'Save your device key',exact:true});await keyDialog.waitFor();assert.equal(await keyDialog.getByLabel('Private API key').getAttribute('type'),'password');
 await keyDialog.getByRole('button',{name:'Reveal key',exact:true}).click();assert.equal(await keyDialog.getByLabel('Private API key').inputValue(),visibleKey);
 await keyDialog.getByRole('button',{name:'I have saved the key',exact:true}).click();await keyDialog.waitFor({state:'hidden'});assert.equal(await page.getByLabel('Private API key').inputValue(),'');
 await page.getByRole('button',{name:'Rotate key',exact:true}).click();await page.getByRole('dialog',{name:'Rotate device key'}).getByRole('button',{name:'Rotate and reveal key'}).click();
 await keyDialog.waitFor();assert.equal(await keyDialog.getByLabel('Private API key').getAttribute('type'),'password');await keyDialog.getByRole('button',{name:'I have saved the key'}).click();
 await page.getByRole('button',{name:'Revoke device',exact:true}).click();await page.getByRole('dialog',{name:'Revoke SMS device'}).getByRole('button',{name:'Revoke device',exact:true}).click();await page.getByRole('dialog',{name:'Revoke SMS device'}).waitFor({state:'hidden'});
 assert.equal(devices.find(row=>row.id===72).is_active,false);
 await page.getByRole('row',{name:/^Fixture phone Device 71/}).click();await page.getByRole('button',{name:'Edit device',exact:true}).click();
 const editDialog=page.getByRole('dialog',{name:'Edit SMS device',exact:true});await editDialog.getByLabel('Device name').fill('Retained revised phone');await editDialog.getByRole('button',{name:'Save device',exact:true}).click();await editDialog.getByRole('alert').waitFor();
 assert.equal(await editDialog.getByLabel('Device name').inputValue(),'Retained revised phone');await editDialog.getByRole('button',{name:'Close dialog',exact:true}).click();
 await page.getByRole('button',{name:'Refresh devices',exact:true}).click();await page.getByRole('row',{name:/^Fixture phone Device 71/}).click();await page.getByRole('button',{name:'Edit device',exact:true}).click();await editDialog.getByRole('button',{name:'Use latest selected revision',exact:true}).click();
 assert.equal(await editDialog.getByLabel('Device name').inputValue(),'Retained revised phone');await editDialog.getByRole('button',{name:'Save device',exact:true}).click();await editDialog.waitFor({state:'hidden'});assert.equal(editAttempts,2);
 await page.goto(origin+'/subscriptions?customer_id=101&subscription_id=999');await page.getByText('Subscription details',{exact:true}).waitFor();await page.getByRole('button',{name:'Check expiry and quota'}).waitFor();
 assert(requests.some(row=>row.path==='/v1/admin/subscriptions/999'));
 await page.evaluate(async()=>{await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/subscriptions?customer_id=102&subscription_id=999');});await page.getByRole('alert').filter({hasText:'does not belong to the selected customer'}).waitFor();assert.equal(await page.getByRole('button',{name:'Check expiry and quota'}).count(),0);
 assert.deepEqual(errors,[]);
 console.log('PASS: role modal failure/retry draft, approved payment provenance, SMS enrollment failure/retry, actual destination and typed request, hidden one-time key cleanup, rotation/revocation revisions, explicit revision-conflict draft recovery, subscription deep-link parent boundary');
}finally{await page.close();await browser.close();}
