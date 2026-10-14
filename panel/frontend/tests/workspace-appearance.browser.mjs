// Actual Vue rendering with empty, controlled API responses; no business writes.
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const context=await browser.newContext({viewport:{width:1440,height:1080},reducedMotion:'reduce'});
const page=await context.newPage(),errors=[];
page.setDefaultTimeout(8000);
page.on('pageerror',error=>errors.push(error.message));
const list={data:[],meta:{pager:{total_items:0,total_pages:1,current_page:1,per_page:20,has_prev:false,has_next:false}}};
const defaults={
 quota_policy:{mode:'reported',grant_bytes:1024,grant_seconds:30,report_max_age_seconds:60,report_future_seconds:5},
 fulfillment:{renewal_trigger:'either',automatic:false,activation:'all',minimum_successes:1,expiry_start:'activation',failure_action:'hold',max_attempts:3,claim_seconds:30,retry_seconds:5,deadline_minutes:10,renewal_quota:'reset',renewal_price:'purchased'},
 ip_limit:{enabled:false,mode:'reject_new',max_ips:2,lease_seconds:120,ban_seconds:300},
};
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);
 assert.equal(request.method(),'GET','Visual previews must not write records');
 const data=path==='/v1/admin/auth/me'
  ? {username:'preview',scopes:['*'],csrf_token:'controlled-preview-token'}
  : path==='/v1/admin/branding'
   ? {data:{brand_title:'Papilio'}}
   : path==='/v1/admin/plans/policy-defaults'
    ? {data:defaults}
    : path==='/v1/admin/customers/creation-policy'
     ? {data:{is_active:true,services_enabled:true,renewals_enabled:true}}
     : list;
 return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
});
try{
 await mkdir('.local-review/appearance',{recursive:true});
 await page.goto(process.env.PANEL_ORIGIN+'/');
 await page.getByRole('heading',{name:'Overview',exact:true}).waitFor();
 assert.equal(await page.locator('html').evaluate(el=>getComputedStyle(el).getPropertyValue('--accent').trim()),'#f5f5f5');
 assert.equal(await page.locator('.brand .papilio-logo-dark').getAttribute('src'),'/papilio-logo-dark.png');
 assert.equal(await page.locator('meta[name="theme-color"]').getAttribute('content'),'#080808');
 const brandBounds=await page.locator('.brand .papilio-logo-dark').boundingBox();
 assert(brandBounds&&brandBounds.width<=200,'The full Papilio logo must fit the navigation rail');
 assert.equal(await page.locator('body').evaluate(el=>getComputedStyle(el,'::before').zIndex),'0');
 await page.getByText('Registered customer accounts',{exact:true}).waitFor();
 await page.waitForFunction(()=>{
  const values=[...document.querySelectorAll('.stat .value')];
  return values.length===3&&values.every(value=>value.textContent.trim()==='0');
 });
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:'.local-review/appearance/dashboard-dark-en.png',fullPage:true,animations:'disabled'});
 await page.getByTestId('theme-selector').selectOption('light');
 assert.equal(await page.locator('html').evaluate(el=>getComputedStyle(el).getPropertyValue('--accent').trim()),'#202020');
 assert.equal(await page.locator('.brand .papilio-logo-light').evaluate(el=>getComputedStyle(el).display),'block');
 assert.equal(await page.locator('meta[name="theme-color"]').getAttribute('content'),'#f4f4f4');
 await page.screenshot({path:'.local-review/appearance/dashboard-light-en.png',fullPage:true,animations:'disabled'});
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('heading',{name:'نمای کلی',exact:true}).waitFor();
 await page.getByTestId('theme-selector').selectOption('dark');
 await page.screenshot({path:'.local-review/appearance/dashboard-dark-fa.png',fullPage:true,animations:'disabled'});
 await page.getByTestId('locale-selector').selectOption('en');
 await page.goto(process.env.PANEL_ORIGIN+'/plans');
 await page.getByRole('button',{name:'+ Create plan',exact:true}).click();
 const modal=page.getByRole('dialog',{name:'Create plan',exact:true});
 await modal.getByLabel('Display name',{exact:true}).fill('Preview draft');
 await modal.getByLabel('Plan type',{exact:true}).selectOption('quota_only');
 assert.equal(await modal.getByLabel('Duration (days)',{exact:true}).count(),0);
 await modal.getByLabel('Override delivery and renewal policy',{exact:true}).check();
 assert(await modal.getByLabel('Override delivery and renewal policy',{exact:true}).isChecked());
 await page.screenshot({path:'.local-review/appearance/plan-modal-dark.png',animations:'disabled'});
 await modal.getByRole('button',{name:'Close dialog',exact:true}).click();
 await page.setViewportSize({width:390,height:844});
 await page.goto(process.env.PANEL_ORIGIN+'/');
 await page.getByRole('heading',{name:'Overview',exact:true}).waitFor();
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:'.local-review/appearance/dashboard-mobile.png',fullPage:true,animations:'disabled'});
 await page.goto(process.env.PANEL_ORIGIN+'/login');
 // An authenticated visitor is redirected to overview; clear the controlled principal.
 await page.route('**/api/v1/admin/auth/me',route=>route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({error:{message_code:'admin_unauthorized'}})}));
 await page.reload();
 await page.goto(process.env.PANEL_ORIGIN+'/login');
 await page.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();
 await page.screenshot({path:'.local-review/appearance/login-mobile-dark.png',animations:'disabled'});
 await page.setViewportSize({width:1440,height:1000});
 await page.screenshot({path:'.local-review/appearance/login-desktop-dark.png',animations:'disabled'});
 assert.deepEqual(errors,[]);
 console.log('PASS: dashboard in both themes/languages, mobile fit, plan modal and native checkbox; controlled HTTP');
}finally{
 await context.close();
 await browser.close();
}
