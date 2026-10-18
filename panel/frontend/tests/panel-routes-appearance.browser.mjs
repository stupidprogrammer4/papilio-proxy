import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';

const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'}),errors=[],reads=[];
page.setDefaultTimeout(2500);
const list={data:[],meta:{pager:{total_items:0,total_pages:1,current_page:1,per_page:20,has_prev:false,has_next:false}}};
const customerList={data:[{id:7,display_name:'Unified customer',telegram_id:123,is_active:true,services_enabled:true,renewals_enabled:true,service_hold_pending:false,service_hold_clock:null}],meta:{pager:{total_items:21,total_pages:2,current_page:1,per_page:20,has_prev:false,has_next:true}}};
const nodeList={data:[{id:9,code:'unified-node',label:'Unified node',public_host:'node.example.test',public_port:443,protocol:'vless_reality',is_enabled:true}],meta:{pager:{total_items:21,total_pages:2,current_page:1,per_page:20,has_prev:false,has_next:true}}};
let currentLocale='en';
const schedule={key:'payments',revision:1,mode:'interval',interval_seconds:60,enabled:true,cron:null,timezone:null,batch_size:20,recheck_seconds:30,capacity_valid:true,applied_revision:1,registered_at:'2026-10-13T00:00:00Z'};
const routes=['/','/customers','/plans','/subscriptions','/loyalty','/payments','/network','/configurations','/connection-lab','/host-groups','/automation','/notifications','/support','/resellers','/roles','/staff','/settings','/customers/1/wallet','/network/1/cores','/network/1/cores/2/configurations','/reseller/customers'];
const titles={'/loyalty':['Loyalty & discounts','وفاداری و تخفیف'],'/host-groups':['Delivery groups','گروه‌های تحویل'],'/notifications':['Notifications','اعلان‌ها'],'/resellers':['Resellers','نماینده‌ها'],'/roles':['Roles','نقش‌ها'],'/staff':['Team and access','تیم و دسترسی'],'/customers/1/wallet':['Wallet activity','گردش کیف پول']};
page.on('pageerror',error=>errors.push(error.stack||error.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),requestUrl=new URL(request.url()),path=requestUrl.pathname.slice(4);
 assert.equal(request.method(),'GET','The route appearance sweep must not write records');
 reads.push(path+requestUrl.search);
 const data=path==='/v1/reseller/auth/me'
  ? {reseller_id:1,account_id:1,title:'Test reseller',username:'test',scopes:['*'],csrf_token:'controlled-reseller-token'}
  : path==='/v1/reseller/profile'
   ? {data:{id:1,code:'test',title:'Test reseller',revision:1,wallet_customer_id:1,login_enabled:true,sales_enabled:true,renewals_enabled:true,policy:{require_active_owner:true,customer_creation_enabled:true,customer_access_override_enabled:true,new_customer_access:{is_active:true,services_enabled:true,renewals_enabled:true},customer_capacity:20,account_capacity:2,plan_capacity:20,max_sessions_per_account:2,session_limit_mode:'reject_new',payer_mode:'either',customer_self_purchase:true,renewal_price_mode:'purchase_snapshot',renewal_availability_mode:'purchase_snapshot',customer_can_disable_reseller_renewal:true}}}
   : path==='/v1/admin/auth/me'
  ? {username:'preview',scopes:['*'],csrf_token:'controlled-preview-token'}
  : path==='/v1/admin/branding'
   ? {data:{brand_title:'Papilio'}}
   : path==='/v1/admin/resellers/scope-catalog'
    ? {data:{areas:['resellers','team','wallet','staff','customers','catalog','payments','subscriptions','network','settings','support','notifications'],levels:['read','create','update','delete','manage']}}
   : path==='/v1/admin/staff/scope-catalog'
    ? {data:{areas:['staff','customers','catalog','payments','subscriptions','network','settings','support','notifications','resellers'],levels:['read','create','update','delete','manage']}}
   : path==='/v1/admin/resellers/defaults'
    ? {data:{access:{login_enabled:true,sales_enabled:true,renewals_enabled:true},policy:{require_active_owner:true,customer_creation_enabled:true,customer_access_override_enabled:true,new_customer_access:{is_active:true,services_enabled:true,renewals_enabled:true},customer_capacity:20,account_capacity:2,plan_capacity:20,max_sessions_per_account:2,session_limit_mode:'reject_new',payer_mode:'either',customer_self_purchase:true,renewal_price_mode:'purchase_snapshot',renewal_availability_mode:'purchase_snapshot',customer_can_disable_reseller_renewal:true},owner_access:{scopes:[]},owner_is_active:true,wallet_customer_access:{is_active:true,services_enabled:true,renewals_enabled:true}}}
  : path==='/v1/admin/automation/schedules'
   ? {data:[schedule]}
   : path==='/v1/admin/settings'
    ? {data:{revision:1,capabilities:{checkout_transient_conflict_modes:['retry_until_expiry','require_confirmation']},values:{brand_title:'Papilio',payment_instructions:null,support_handle:null,topup_options_rial:[120000],customer_creation_access:{is_active:true,services_enabled:true,renewals_enabled:true},customer_link_rotation:false,receipts:{enabled:false,max_per_topup:1,allowed_formats:['PNG']},checkout:{destination_mode:'required',allowed_methods:['card'],minimum_topup_rial:10000,maximum_topup_rial:500000},purchase_checkout:{enabled:false,admission_mode:'require_ready_bundle',default_expiry_seconds:900},qr_codes:{enabled:true,error_correction:'M',box_size:4,border_modules:2},quota_policy:{mode:'reported',grant_bytes:1024,grant_seconds:60,report_max_age_seconds:60,report_future_seconds:5},fulfillment:{renewal_trigger:'expiry',automatic:false,activation:'all',minimum_successes:1,expiry_start:'purchase',failure_action:'hold',max_attempts:3,claim_seconds:60,retry_seconds:60,deadline_minutes:5,renewal_quota:'reset',renewal_price:'purchased'},ip_defaults:{enabled:false,mode:'reject_new',max_ips:2,lease_seconds:60,ban_seconds:60},max_plan_duration_days:365,payment_stale_hours:24,node_health_stale_seconds:60,subscription_expiry_warning_hours:24,provisioning_attention_minutes:5}}}
    : path==='/v1/admin/network/nodes/1'
     ? {data:{id:1,code:'route-fixture-node',label:currentLocale==='fa'?'نود':'Node',public_host:'fixture.invalid',public_port:443,protocol:'vless_reality',is_enabled:true}}
      : path==='/v1/admin/network/cores/2'
      ? {data:{id:2,node_id:1,code:'route-fixture-core',label:'Route fixture core',kind:'xray',supported_protocols:['vless_reality'],application_status:'draft'}}
      : path==='/v1/admin/customers'
       ? {...customerList,data:[{...customerList.data[0],display_name:currentLocale==='fa'?'مشتری یکپارچه':'Unified customer'}]}
       : path==='/v1/admin/network/nodes'
        ? {...nodeList,data:[{...nodeList.data[0],label:currentLocale==='fa'?'سرور یکپارچه':'Unified node'}]}
        : list;
 return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
});
try{
 for(const locale of ['en','fa']){
  currentLocale=locale;
  await page.goto(process.env.PANEL_ORIGIN+'/');
  await page.getByTestId('locale-selector').selectOption(locale);
  await page.getByTestId('theme-selector').selectOption(locale==='en'?'dark':'light');
  for(const path of routes){
   await page.goto(process.env.PANEL_ORIGIN+path);
   await page.locator('main h1').first().waitFor();
   await page.waitForLoadState('networkidle');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Horizontal overflow at ${locale} ${path}`);
   assert.equal(await page.locator('html').getAttribute('lang'),locale,`Language mismatch at ${path}`);
   assert.equal(await page.locator('html').getAttribute('dir'),locale==='fa'?'rtl':'ltr',`Direction mismatch at ${path}`);
   if(path==='/'){
    if(locale==='en'){
     await page.getByRole('heading',{name:'Customers and servers',exact:true}).waitFor();
     await page.getByText('Unified customer',{exact:true}).waitFor();
     await page.getByText('Unified node',{exact:true}).waitFor();
     const customerSearch=page.waitForRequest(request=>request.url().includes('/v1/admin/customers?q=unified&page=1'));
     await page.getByLabel('Search customers').fill('unified');
     await customerSearch;
     const serverSearch=page.waitForRequest(request=>request.url().includes('/v1/admin/network/nodes?q=edge&page=1'));
     await page.getByLabel('Search servers').fill('edge');
     await serverSearch;
     const customerNext=page.waitForRequest(request=>request.url().includes('/v1/admin/customers?q=unified&page=2'));
     await page.getByRole('button',{name:'Next customer page'}).click();
     await customerNext;
     const serverNext=page.waitForRequest(request=>request.url().includes('/v1/admin/network/nodes?q=edge&page=2'));
     await page.getByRole('button',{name:'Next server page'}).click();
     await serverNext;
     assert(reads.some(value=>value.includes('/v1/admin/customers?q=unified&page=1')),`Dashboard customer search must use the customer API: ${reads.filter(value=>value.includes('/v1/admin/customers')).join(', ')}`);
     assert(reads.some(value=>value.includes('/v1/admin/customers?q=unified&page=2')),'Dashboard customer pagination must stay independent');
     assert(reads.some(value=>value.includes('/v1/admin/network/nodes?q=edge&page=1')),'Dashboard server search must use the node API');
     assert(reads.some(value=>value.includes('/v1/admin/network/nodes?q=edge&page=2')),'Dashboard server pagination must stay independent');
    }
    if(locale==='fa'){
     await page.getByRole('heading',{name:'مشتری‌ها و سرورها',exact:true}).waitFor();
     await page.getByText('مشتری یکپارچه',{exact:true}).waitFor();
     await page.getByText('سرور یکپارچه',{exact:true}).waitFor();
    }
   }
   if(path==='/network'){
    assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'نودها و کیفیت اتصال':'Nodes and connection quality');
    await page.getByRole('heading',{name:locale==='fa'?'نودهای ثبت‌شده':'Registered nodes',exact:true}).waitFor();
    await page.getByRole('heading',{name:locale==='fa'?'اندازه‌گیری اتصال':'Connection measurements',exact:true}).waitFor();
   }
   if(path==='/connection-lab'){
    assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'بررسی شواهد اتصال':'Inspect connection evidence');
    await page.getByRole('heading',{name:locale==='fa'?'انتخاب نود ثبت‌شده':'Choose a registered node',exact:true}).waitFor();
    await page.getByRole('heading',{name:locale==='fa'?'مقایسهٔ شبکه‌های مبدأ ثبت‌شده':'Recorded source-network comparison',exact:true}).waitFor();
    await page.getByRole('heading',{name:locale==='fa'?'ابزارهای پیشرفته':'Advanced tools',exact:true}).waitFor();
   }
   if(path==='/reseller/customers'){
    assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'مشتریان نماینده':'Reseller customers');
    await page.getByLabel(locale==='fa'?'جست‌وجوی مشتریان':'Search customers').waitFor();
    await page.getByRole('columnheader',{name:locale==='fa'?'حساب / سرویس / تمدید':'Account / service / renewal',exact:true}).waitFor();
    await page.getByRole('button',{name:locale==='fa'?'ساخت مشتری':'Create customer'}).click();
    await page.getByRole('dialog').getByRole('heading',{name:locale==='fa'?'ساخت مشتری':'Create customer'}).waitFor();
    await page.getByLabel(locale==='fa'?'نام':'Name', {exact:true}).waitFor();
   }
   if(path==='/roles'){
    await page.getByLabel(locale==='fa'?'جست‌وجوی نام یا کد نقش':'Search role name or code').waitFor();
    await page.getByRole('columnheader',{name:locale==='fa'?'نقش':'Role',exact:true}).waitFor();
   }
   if(path==='/customers')assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'مشتری‌ها':'Customers');
   if(path==='/subscriptions'){
    assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'اشتراک‌ها':'Subscriptions');
    await page.getByRole('heading',{name:locale==='fa'?'جزئیات اشتراک':'Subscription details',exact:true}).waitFor();
   }
   if(path==='/settings'){
    assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'تنظیمات':'Settings');
    await page.getByLabel(locale==='fa'?'نام برند':'Brand name').waitFor();
    await page.getByRole('region',{name:locale==='fa'?'سیاست خرید خودکار':'Automated purchase policy'}).waitFor();
    await page.getByLabel(locale==='fa'?'فعال‌کردن خرید خودکار':'Enable automated checkout').waitFor();
    await page.getByText(locale==='fa'?'کد QR اتصال':'Connection QR code',{exact:true}).waitFor();
    await page.getByLabel(locale==='fa'?'انتخاب مقصد پرداخت':'Payment destination selection').waitFor();
   }
   if(path==='/automation'){
    await page.getByRole('heading',{name:locale==='fa'?'زمان‌بندی اتوماسیون':'Automation schedules',exact:true}).waitFor();
    await page.getByRole('columnheader',{name:locale==='fa'?'اقدام‌ها':'Actions',exact:true}).first().waitFor();
    await page.getByRole('row').filter({hasText:locale==='fa'?'تطبیق پرداخت':'Payment reconciliation'}).click();
    await page.getByLabel(locale==='fa'?'حالت زمان‌بندی':'Schedule mode').waitFor();
    await page.getByRole('heading',{name:locale==='fa'?'سلامت نود':'Node health',exact:true}).waitFor();
    await page.getByRole('heading',{name:locale==='fa'?'تطبیق پرداخت':'Payment reconciliation',exact:true}).waitFor();
    await page.getByRole('heading',{name:locale==='fa'?'اشتراک‌های نیازمند رسیدگی':'Subscriptions needing attention',exact:true}).waitFor();
   }
   if(path==='/automation')assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'اتوماسیون':'Automation');
   if(path==='/configurations'){assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'کانفیگ‌ها':'Configurations');await page.getByRole('heading',{name:locale==='fa'?'پیش‌نویس‌های کانفیگ':'Configuration drafts',exact:true}).waitFor();}
   if(path==='/host-groups'){await page.getByLabel(locale==='fa'?'جست‌وجوی گروه‌ها':'Search groups').waitFor();await page.getByRole('columnheader',{name:locale==='fa'?'عنوان':'Label',exact:true}).waitFor();}
   if(path==='/support'){
    assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'پشتیبانی':'Support');
    await page.getByRole('heading',{name:locale==='fa'?'درخواست‌ها':'Tickets',exact:true}).waitFor();
    await page.getByLabel(locale==='fa'?'جست‌وجوی موضوع':'Search subject').waitFor();
   }
   if(path==='/resellers'){
    await page.getByRole('columnheader',{name:locale==='fa'?'نماینده':'Reseller',exact:true}).waitFor();
    await page.getByLabel(locale==='fa'?'جست‌وجوی کد یا نام':'Search code or name').waitFor();
   }
   if(titles[path])assert.equal(await page.locator('main h1').first().innerText(),titles[path][locale==='fa'?1:0]);
   if(path==='/network/1/cores'){
    assert.equal(await page.locator('main h1').first().innerText(),locale==='fa'?'هسته‌های نود':'Cores for Node');
    await page.getByRole('columnheader',{name:locale==='fa'?'آخرین وضعیت گزارش‌شده':'Last reported state',exact:true}).waitFor();
   }
  }
 }
 assert.deepEqual(errors,[]);
 console.log(`PASS: ${routes.length} routes in English/dark and Persian/light at 390px; ${reads.length} controlled GETs, no write requests or page errors`);
}finally{await browser.close();}
