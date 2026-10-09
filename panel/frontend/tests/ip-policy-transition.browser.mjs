// Actual Vue with controlled typed HTTP; physical closure and native enforcement are not exercised.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],writes=[];
const current={enabled:true,max_ips:3,lease_seconds:45,ban_seconds:75,mode:'reject_new'};
const target={...current,max_ips:1};
const purchased={policy:current,source:'plan_override',plan_id:42,captured_at:'2026-10-01T00:00:00Z'};
const effective={policy:current,source:'subscription_override',scope:'subscription',enforcement:'api_admission_only',core_enforcement_verified:false,transition:null};
const subscription={id:91,customer_id:31,plan_id:42,entitlement_kind:'paid',quota_bytes:5368709120,used_bytes:0,price_rial:100000,duration_days:30,expires_at:'2026-11-01T00:00:00Z',status:'active',auto_renew:false,renewal_count:0,failure_reason:null,provisioning_managed:false,activated_at:'2026-10-01T00:00:00Z',group_id:null,suspended_at:null,suspension_clock:null,suspension_reason:null,suspended_by_staff_id:null,suspended_by_reseller_account_id:null,purchased_ip_policy:purchased,effective_ip_policy:effective};
const detail={subscription_id:91,policy:{subscription_id:91,...current},purchased_ip_policy:purchased,effective_ip_policy:effective,defaults:{...current,max_ips_ceiling:40,max_lease_seconds:300,max_ban_seconds:600}};
detail.transition_options={default_mode:'drain_leases',choices:[{mode:'drain_leases',available:true,reason:null},{mode:'require_closed_receipts',available:false,reason:'closed_receipts_unavailable'}]};
let failWrite=false,scopes=['subscriptions:read','subscriptions:update','customers:read'];
const respond=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
const paged=data=>({data,meta:{pager:{total_pages:1,total_items:data.length}}});
page.on('pageerror',error=>errors.push(error.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);
 if(request.method()!=='GET')writes.push({path,body:request.postDataJSON()});
 if(path==='/v1/admin/auth/me')return respond(route,{username:'controlled-ip-review',scopes,csrf_token:'controlled'});
 if(path==='/v1/admin/preferences')return respond(route,{data:{revision:0,values:{brand_title:'Papilio'}}});
 if(path==='/v1/admin/subscriptions')return respond(route,paged([subscription]));
 if(path==='/v1/admin/subscriptions/91')return respond(route,{data:subscription});
 if(path==='/v1/admin/subscriptions/91/ip-limit'){
  if(request.method()==='PUT'){
   if(failWrite)return respond(route,{detail:'Controlled retry failure'},503);
   const {transition_mode,...requested}=request.postDataJSON();
   detail.policy={subscription_id:91,...requested};
   effective.transition={status:'draining',target_policy:requested,mode:transition_mode,retry_at:'2026-10-09T12:00:00Z',reason:'ip_policy_draining'};
   return respond(route,{data:{...detail.policy,transition:effective.transition}});
  }
  return respond(route,{data:detail});
 }
 if(path==='/v1/admin/customers/31')return respond(route,{data:{id:31,display_name:'Controlled owner',telegram_id:null,is_active:true,services_enabled:true,renewals_enabled:true,service_hold_pending:false,service_hold_clock:null}});
 return respond(route,paged([]));
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/subscriptions?customer_id=31&subscription_id=91');
 const region=page.getByRole('region',{name:'Limit IP Subscription'});
 await region.getByText('No IP records match this filter.',{exact:true}).waitFor();
 assert.equal(await region.getByRole('region',{name:'Pending source IP policy'}).count(),0);
 assert.equal(await region.getByLabel('When tightening the allowance',{exact:true}).inputValue(),'drain_leases');
 assert.equal(await region.getByRole('option',{name:'Require verified connection-closure receipts — unavailable',exact:true}).evaluate(option=>option.disabled),true);
 await region.getByLabel('Maximum concurrent IPs',{exact:true}).fill('1');
 await region.getByRole('button',{name:'Save IP policy',exact:true}).click();
 const pending=region.getByRole('region',{name:'Pending source IP policy'});
 await pending.getByText('Waiting for existing leases',{exact:true}).waitFor();
 assert.match(await region.innerText(),/Current API admission allowance: Up to 3 source IPs/);
 assert.match(await pending.innerText(),/Requested allowance\s*1 source IP/);
 await pending.getByText('Earliest retry',{exact:true}).waitFor();
 assert.match(await pending.innerText(),/does not confirm immediate disconnection/);
 assert.equal(writes.length,1);assert.equal(writes[0].path,'/v1/admin/subscriptions/91/ip-limit');assert.deepEqual(writes[0].body,{...target,transition_mode:'drain_leases'});
 await page.getByRole('region',{name:'Subscription source IP allowance'}).getByRole('region',{name:'Pending source IP policy'}).waitFor();
 failWrite=true;
 await region.getByLabel('Maximum concurrent IPs',{exact:true}).fill('2');
 await region.getByRole('button',{name:'Save IP policy',exact:true}).click();
 await region.getByRole('alert').waitFor();
 assert.equal(await region.getByLabel('Maximum concurrent IPs',{exact:true}).inputValue(),'2');
 assert.match(await pending.innerText(),/Requested allowance\s*1 source IP/);
 failWrite=false;
 effective.transition={status:'blocked',target_policy:target,mode:'drain_leases',retry_at:null,reason:'legacy_lease_history_unknown'};
 await region.getByRole('button',{name:'Refresh IPs',exact:true}).click();
 await pending.getByText('Blocked',{exact:true}).waitFor();
 assert.match(await pending.innerText(),/no complete lease history/);assert.equal(await pending.getByText('Earliest retry',{exact:true}).count(),0);
 effective.transition={...effective.transition,mode:'require_closed_receipts',reason:'closed_receipts_unavailable'};
 await region.getByRole('button',{name:'Refresh IPs',exact:true}).click();
 await pending.getByText('Activation requires verified closure receipts; it is unavailable from this panel.',{exact:true}).waitFor();
 assert.equal(await pending.getByRole('button').count(),0);
 assert(await region.getByRole('button',{name:'Save IP policy',exact:true}).isDisabled());
 await region.getByLabel('When tightening the allowance',{exact:true}).selectOption('drain_leases');
 assert(await region.getByRole('button',{name:'Save IP policy',exact:true}).isEnabled());
 assert.match(await region.innerText(),/Current API admission allowance: Up to 3 source IPs/);
 scopes=['subscriptions:read','customers:read'];await page.reload();await region.getByText('No IP records match this filter.',{exact:true}).waitFor();
 assert.equal(await region.getByRole('button',{name:'Save IP policy',exact:true}).count(),0);assert.match(await pending.innerText(),/Blocked/);
 await page.setViewportSize({width:390,height:844});assert(await pending.evaluate(el=>el.getBoundingClientRect().width<=innerWidth));
 assert.deepEqual(errors,[]);assert.equal(writes.length,2);
 console.log(JSON.stringify({boundary:'actual Vue, controlled typed IP transition HTTP',cases:6,writes:2,pageErrors:0}));
}finally{await browser.close();}
