// Actual Vue, controlled declared HTTP contracts; this does not prove core enforcement.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],writes=[],customerReads=[];
const policy={enabled:true,max_ips:2,lease_seconds:45,ban_seconds:75,mode:'reject_new'};
const cap={max_ips_ceiling:4,max_lease_seconds:300,max_ban_seconds:600};
const defaults={quota_policy:{mode:'reported',grant_bytes:1024,grant_seconds:60,report_max_age_seconds:60,report_future_seconds:5},fulfillment:{renewal_trigger:'expiry',automatic:false,activation:'all',minimum_successes:1,expiry_start:'purchase',failure_action:'hold',max_attempts:3,claim_seconds:60,retry_seconds:60,deadline_minutes:5,renewal_quota:'reset',renewal_price:'purchased'},ip_limit:policy,ip_limit_capacity:cap};
const projected=(policy,source)=>({policy,source,scope:'subscription',enforcement:'api_admission_only',core_enforcement_verified:false});
const plan={id:42,code:'old-plan',title:'Legacy plan',quota_bytes:5368709120,duration_days:30,price_rial:100000,sort_order:0,is_active:true,group_id:null,quota_policy:null,fulfillment:null,ip_limit:null,effective_ip_policy:projected(policy,'current_defaults')};
const bought={policy:{...policy,max_ips:1},source:'plan_override',plan_id:42,captured_at:'2026-10-01T00:00:00Z'};
const subscription={id:91,customer_id:31,plan_id:42,entitlement_kind:'paid',quota_bytes:5368709120,used_bytes:0,price_rial:100000,duration_days:30,expires_at:'2026-11-01T00:00:00Z',status:'active',auto_renew:false,renewal_count:0,failure_reason:null,provisioning_managed:false,activated_at:'2026-10-01T00:00:00Z',group_id:null,suspended_at:null,suspension_clock:null,suspension_reason:null,suspended_by_staff_id:null,suspended_by_reseller_account_id:null,purchased_ip_policy:bought,effective_ip_policy:projected({...policy,max_ips:3},'subscription_override')};
const customer=id=>({id,display_name:`Customer ${id}`,telegram_id:null,is_active:true,services_enabled:true,renewals_enabled:true,service_hold_pending:false,service_hold_clock:null});
const paged=(data,total=data.length,pages=1)=>({data,meta:{pager:{total_items:total,total_pages:pages}}});
const respond=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
let failFirst=true,failDefaults=false,failCustomers=false,projectionMode="modern",currentMax=3;
const currentSubscription=()=>{if(projectionMode==="legacy")return {...subscription,purchased_ip_policy:null,effective_ip_policy:projected(null,"legacy_unrestricted")};if(projectionMode==="unknown"){const {purchased_ip_policy,effective_ip_policy,...original}=subscription;return original;}return {...subscription,effective_ip_policy:projected({...policy,max_ips:currentMax},"subscription_override")};};
page.on('pageerror',error=>errors.push(error.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const req=route.request(),url=new URL(req.url()),path=url.pathname.slice(4),method=req.method();
 if(path==='/v1/admin/auth/me')return respond(route,{username:'controlled-allowances',scopes:['*'],csrf_token:'controlled'});
 if(path==='/v1/admin/preferences')return respond(route,{data:{revision:0,values:{brand_title:'Papilio'}}});
 if(path==='/v1/admin/plans/policy-defaults')return failDefaults?respond(route,{error:{message_code:'request_failed'}},503):respond(route,{data:defaults});
 if(path==='/v1/admin/plans'&&method==='POST'){
  const body=req.postDataJSON();writes.push(body);
  if(failFirst){failFirst=false;return respond(route,{error:{message_code:'request_failed'}},503);}
  return respond(route,{data:{...plan,...body,id:100+writes.length,is_active:false}});
 }
 if(path==='/v1/admin/plans/42'&&method==='PATCH'){writes.push(req.postDataJSON());return respond(route,{data:plan});}
 if(path==='/v1/admin/plans')return respond(route,paged([plan]));
 if(path==='/v1/admin/subscriptions')return respond(route,paged([currentSubscription()]));
 if(path==='/v1/admin/subscriptions/91')return respond(route,{data:currentSubscription()});
 if(path==='/v1/admin/subscriptions/91/ip-limit'&&method==='PUT'){const body=req.postDataJSON();assert.equal(body.max_ips,2);currentMax=body.max_ips;return respond(route,{data:{subscription_id:91,...body}});}
 if(path==='/v1/admin/subscriptions/91/ip-limit')return respond(route,{data:{subscription_id:91,policy:{subscription_id:91,...policy,max_ips:currentMax},defaults:{...policy,...cap}}});
 if(path==='/v1/admin/customers/31')return respond(route,{data:customer(31)});
 if(path==='/v1/admin/customers'){
  customerReads.push(url.search);if(failCustomers)return respond(route,{error:{message_code:'request_failed'}},503);return respond(route,paged([customer(url.searchParams.get('page')==='2'?33:31)],2,2));
 }
 return respond(route,paged([]));
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/plans');
 for(const [selection,count] of [['one',1],['custom',3],['unlimited',2]]){
  await page.getByRole('button',{name:'+ Create plan',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Create plan',exact:true});
  await dialog.getByLabel('Unique code',{exact:true}).fill(`plan-${selection}`);
  await dialog.getByLabel('Display name',{exact:true}).fill(`Plan ${selection}`);
  await dialog.getByLabel('Data quota (GiB)',{exact:true}).fill('2');
  await dialog.getByLabel('Duration (days)',{exact:true}).fill('30');
  await dialog.getByLabel('Price (toman)',{exact:true}).fill('100');
  await dialog.getByLabel('Display order',{exact:true}).fill('0');
  const submit=dialog.getByRole('button',{name:'Create plan',exact:true});
  assert(await submit.isDisabled(),'new plans must choose explicit concurrency');
  await dialog.getByLabel('Concurrent source IP allowance',{exact:true}).selectOption(selection);
  if(selection==='custom'){
   const field=dialog.getByLabel('Maximum concurrent source IPs',{exact:true});
   await field.fill('5');assert(await submit.isDisabled(),'application capacity must bound N');
   await field.fill('');assert.equal(await field.inputValue(),'');assert(await submit.isDisabled());
   await field.fill(String(count));
  }
  await submit.click();
  if(selection==='one'){
   await dialog.getByRole('alert').waitFor();
   assert.equal(await dialog.getByLabel('Display name',{exact:true}).inputValue(),'Plan one');
   assert.equal(await dialog.getByLabel('Concurrent source IP allowance',{exact:true}).inputValue(),'one');
   const retained=structuredClone(writes.at(-1));await submit.click();assert.deepEqual(writes.at(-1),retained);
  }
  await dialog.waitFor({state:'hidden'});
  assert.equal(writes.at(-1).ip_limit.enabled,selection!=='unlimited');
  assert.equal(writes.at(-1).ip_limit.max_ips,count);
  assert.equal(writes.at(-1).quota_bytes,2*1073741824);assert.equal(writes.at(-1).price_rial,1000);
 }
 await page.getByRole('button',{name:'Edit',exact:true}).click();
 const edit=page.getByRole('dialog',{name:'Edit plan',exact:true});
 assert.equal(await edit.getByLabel('Concurrent source IP allowance',{exact:true}).inputValue(),'legacy');
 await edit.getByRole('button',{name:'Save plan',exact:true}).click();await edit.waitFor({state:'hidden'});assert.equal(writes.at(-1).ip_limit,null);
 await page.goto(process.env.PANEL_ORIGIN+'/subscriptions?customer_id=31&subscription_id=91');
 const summary=page.getByRole('region',{name:'Subscription source IP allowance'});
 await summary.getByText('1 source IP',{exact:true}).waitFor();await summary.getByText('Up to 3 source IPs',{exact:true}).waitFor();
 assert.match(await summary.innerText(),/Recorded operational policy/);assert.doesNotMatch(await summary.innerText(),/Administrator override/);
 await summary.getByText('This operational override does not rewrite the purchased snapshot.',{exact:true}).waitFor();
 const admission=page.getByRole('region',{name:'Limit IP Subscription'});await admission.getByLabel('Maximum concurrent IPs',{exact:true}).fill('2');await admission.getByRole('button',{name:'Save IP policy',exact:true}).click();await summary.getByText('Up to 2 source IPs',{exact:true}).waitFor();assert.equal(await summary.getByText('1 source IP',{exact:true}).count(),1);
 const picker=page.getByRole('region',{name:'Customer selection'});await picker.getByText('Customer context: Customer 31 · #31',{exact:true}).waitFor();
 assert.equal(await picker.getByLabel('Find a customer',{exact:true}).count(),0);
 await page.goto(process.env.PANEL_ORIGIN+'/subscriptions');
 const search=page.getByRole('region',{name:'Customer selection'});
 await search.getByRole('button',{name:'Select customer #31',exact:true}).click();
 await search.getByRole('button',{name:'Next customers',exact:true}).click();
 await search.getByRole('button',{name:'Select customer #33',exact:true}).waitFor();
 assert.match(await search.innerText(),/Selected customer: Customer 31 · #31/);assert(customerReads.some(value=>value.includes('page=2')));
 failCustomers=true;await search.getByLabel('Find a customer',{exact:true}).fill('another');await search.getByRole('button',{name:'Search customers',exact:true}).click();await search.getByRole('alert').waitFor();assert.match(await search.innerText(),/Selected customer: Customer 31 · #31/);assert.equal(await search.getByText('No customers match this search.',{exact:true}).count(),0);
 await page.setViewportSize({width:390,height:844});assert(await search.evaluate(el=>el.getBoundingClientRect().width<=innerWidth));
 projectionMode='legacy';await page.goto(process.env.PANEL_ORIGIN+'/subscriptions?customer_id=31&subscription_id=91');const legacy=page.getByRole('region',{name:'Subscription source IP allowance'});await legacy.getByText('Legacy: no purchased snapshot',{exact:true}).waitFor();await legacy.getByText('No recorded source-IP restriction',{exact:true}).waitFor();assert.equal(await legacy.getByText('Unlimited source IPs',{exact:true}).count(),0);
 projectionMode='unknown';await page.reload();await page.getByRole('region',{name:'Subscription source IP allowance'}).getByText('Snapshot unavailable from this API',{exact:true}).waitFor();
 failDefaults=true;await page.goto(process.env.PANEL_ORIGIN+'/plans');
 await page.getByRole('button',{name:'+ Create plan',exact:true}).click();const unavailable=page.getByRole('dialog',{name:'Create plan',exact:true});
 await unavailable.getByRole('button',{name:'Reload defaults',exact:true}).waitFor();assert(await unavailable.getByRole('button',{name:'Create plan',exact:true}).isDisabled());
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({boundary:'actual Vue, controlled declared API',cases:12,planRequests:writes.length,customerPaging:true,pageErrors:0}));
}finally{await browser.close();}
