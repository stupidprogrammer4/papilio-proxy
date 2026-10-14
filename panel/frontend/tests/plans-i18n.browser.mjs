// Actual Plans Vue flow with controlled read-only API responses.
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage({viewport:{width:1440,height:1080},reducedMotion:'reduce'});
const errors=[];
const calls=[];
page.setDefaultTimeout(8000);
page.on('pageerror',error=>errors.push(error.message));
const paged=data=>({data,meta:{pager:{total_items:data.length,total_pages:1,current_page:1,per_page:20,has_prev:false,has_next:false}}});
const defaults={
 quota_policy:{mode:'reported',grant_bytes:1024,grant_seconds:60,report_max_age_seconds:60,report_future_seconds:5},
 fulfillment:{renewal_trigger:'either',automatic:false,activation:'all',minimum_successes:1,expiry_start:'activation',failure_action:'hold',max_attempts:3,claim_seconds:30,retry_seconds:5,deadline_minutes:10,renewal_quota:'reset',renewal_price:'purchased'},
 ip_limit:{enabled:false,mode:'reject_new',max_ips:2,lease_seconds:120,ban_seconds:300},
 ip_limit_capacity:{max_ips_ceiling:8,max_lease_seconds:600,max_ban_seconds:900},
};
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);
 calls.push(`${request.method()} ${path}`);
 assert.equal(request.method(),'GET','This localization flow must remain read-only');
 const data=path==='/v1/admin/auth/me'
  ? {username:'controlled-plans',scopes:['*'],csrf_token:'controlled'}
  : path==='/v1/admin/plans/policy-defaults'
   ? {data:defaults}
   : paged([]);
 return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
});
try{
 await mkdir('.local-review/appearance',{recursive:true});
 await page.goto(`${process.env.PANEL_ORIGIN}/plans`);
 await page.getByRole('heading',{name:'Plans',exact:true}).waitFor();
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('heading',{name:'پلن‌ها',exact:true}).waitFor();
 await page.getByRole('button',{name:/ساخت پلن/}).click();
 const dialog=page.getByRole('dialog',{name:'ساخت پلن',exact:true});
 await dialog.getByLabel('کد یکتا',{exact:true}).waitFor();
 await dialog.getByLabel('نام نمایشی',{exact:true}).waitFor();
 await dialog.getByLabel('نوع پلن',{exact:true}).selectOption('quota_only');
 assert.equal(await dialog.getByLabel('مدت (روز)',{exact:true}).count(),0);
 const fulfillmentToggle=dialog.getByLabel('تنظیم اختصاصی تحویل و تمدید',{exact:true});
 await fulfillmentToggle.waitFor();
 assert(await fulfillmentToggle.isEnabled(),`Fulfillment defaults did not load: ${calls.join(', ')}`);
 await fulfillmentToggle.check();
 await dialog.getByText('شرط فعال‌سازی اشتراک',{exact:true}).waitFor();
 await dialog.getByLabel('حداکثر IP مبدأ هم‌زمان',{exact:true}).selectOption('one');
 await dialog.getByLabel('تنظیم اختصاصی سیاست سهمیه',{exact:true}).check();
 await dialog.getByText('روش اعمال سهمیه',{exact:true}).waitFor();
 assert.equal(await dialog.getByText('Unique code',{exact:true}).count(),0);
 assert.equal(await dialog.getByText('Activation requirement',{exact:true}).count(),0);
 await dialog.locator('.modal-body').evaluate(element=>{element.scrollTop=0;});
 await page.screenshot({path:'.local-review/appearance/plans-create-fa.png',animations:'disabled'});
 assert.deepEqual(errors,[]);
 console.log('PASS: read-only plan catalog and creation flow render translated labels and policy choices');
}finally{await browser.close();}
