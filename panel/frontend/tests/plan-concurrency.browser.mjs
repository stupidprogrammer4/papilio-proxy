// Actual Vue with controlled API responses; no native node enforcement is proven here.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],writes=[];
const policy={enabled:true,max_ips:1,lease_seconds:45,ban_seconds:75,mode:'reject_new'};
const subscription={id:91,customer_id:31,plan_id:42,entitlement_kind:'paid',quota_bytes:5368709120,used_bytes:0,price_rial:100000,duration_days:30,expires_at:'2026-11-01T00:00:00Z',status:'active',auto_renew:false,renewal_count:0,failure_reason:null,provisioning_managed:false,activated_at:'2026-10-01T00:00:00Z',group_id:null,suspended_at:null,suspension_clock:null,suspension_reason:null,suspended_by_staff_id:null,suspended_by_reseller_account_id:null};
const detail={subscription_id:91,policy:{subscription_id:91,...policy},defaults:{...policy,max_ips_ceiling:40,max_lease_seconds:300,max_ban_seconds:600}};
const respond=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
const paged=data=>({data,meta:{pager:{total_pages:1,total_items:data.length}}});
page.on('pageerror',error=>errors.push(error.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);
 if(request.method()!=='GET')writes.push({path,body:request.postDataJSON()});
 if(path==='/v1/admin/auth/me')return respond(route,{username:'controlled-ip-review',scopes:['subscriptions:read','customers:read'],csrf_token:'controlled'});
 if(path==='/v1/admin/preferences')return respond(route,{data:{revision:0,values:{brand_title:'Papilio'}}});
 if(path==='/v1/admin/subscriptions')return respond(route,paged([subscription]));
 if(path==='/v1/admin/subscriptions/91')return respond(route,{data:subscription});
 if(path==='/v1/admin/subscriptions/91/ip-limit')return respond(route,{data:detail});
 if(path==='/v1/admin/customers/31')return respond(route,{data:{id:31,display_name:'Controlled owner',telegram_id:null,is_active:true,services_enabled:true,renewals_enabled:true,service_hold_pending:false,service_hold_clock:null}});
 return respond(route,paged([]));
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/subscriptions?customer_id=31&subscription_id=91');
 const region=page.getByRole('region',{name:'Limit IP Subscription'});
 await region.getByText('No IP records match this filter.',{exact:true}).waitFor();
 const text=await region.innerText();
 assert.match(text,/API admission (decisions|checks) only/i,'recorded API IP policy was presented without a core-enforcement boundary');
 assert.doesNotMatch(text,/Concurrent IP limits are shared across the subscription.s assigned nodes/,'API records were advertised as verified distributed core enforcement');
 assert.match(text,/not (verified|confirmed)/i,'unknown engine enforcement was hidden');
 assert.match(text,/not.*device|device.*not/i,'IP allowance was advertised as device count');
 assert.equal(writes.length,0);assert.deepEqual(errors,[]);
 await page.setViewportSize({width:390,height:844});
 assert(await region.evaluate(el=>el.getBoundingClientRect().width<=innerWidth));
 console.log(JSON.stringify({boundary:'actual Vue, controlled existing IP API',cases:1,writes:0,pageErrors:0}));
}finally{await browser.close();}
