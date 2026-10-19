// Actual Vue consumer with controlled HTTP, not native purchase/settlement evidence.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],writes=[];
let quoteFailed=true,purchaseFailed=true,renewalFailed=true,renewalOther=false;
const topupWrites=[];
const quota=1024**3;
const tier={id:1,code:'silver',title:'Silver',minimum_bytes:200*quota,discount_bps:500,is_enabled:true,revision:1};
const plan={id:42,title:'Selected volume plan',code:'volume',price_rial:111,quota_bytes:5*quota,duration_days:null,is_active:true};
const quote={customer_id:31,plan_id:42,base_price_rial:111,price_rial:101,discount_rial:10,renewal_price_rial:105,tier_code:'silver',tier_discount_bps:500,first_purchase_discount_bps:1000,policy_revision:3};
const respond=(r,data,status=200)=>r.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
const paged=data=>({data,meta:{pager:{total_pages:1}}});
page.on('pageerror',e=>errors.push(e.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);
 if(path==='/v1/customer/auth/me')return respond(route,{customer_id:31,display_name:'Customer',csrf_token:'controlled'});
 if(path==='/v1/customer/wallet')return respond(route,{data:{balance_rial:10000}});
 if(path==='/v1/customer/topups'&&request.method()==='POST'){topupWrites.push(request.postDataJSON());return respond(route,{data:{id:501,revision:1,customer_id:31,amount_rial:10000,requested_amount_rial:10000,payment_identifier_mode:'none',payment_identifier_code4:null,status:'pending',bank_reference:null,approved_by_staff_id:null}});}
 if(path==='/v1/customer/preferences')return respond(route,{data:{brand_title:'Papilio',topup_options_rial:[],checkout:{destination_mode:'legacy',minimum_topup_rial:1,maximum_topup_rial:10000},receipts:{enabled:false}}});
 if(path==='/v1/customer/loyalty')return respond(route,{data:{customer_id:31,purchased_bytes:250*quota,purchase_count:4,lifetime_purchase_count:5,tier,next_tier:{...tier,id:2,title:'Gold',minimum_bytes:700*quota}}});
 if(path==='/v1/customer/plans')return respond(route,paged([plan]));
 if(path==='/v1/customer/plans/42/quote'){
  if(quoteFailed){quoteFailed=false;return respond(route,{error:{message_code:'network'}},503);}
  return respond(route,{data:quote});
 }
 if(path==='/v1/customer/subscriptions'&&request.method()==='POST'){
  const body=request.postDataJSON();writes.push(body);assert.equal(body.expected_price_rial,101);
  if(purchaseFailed){purchaseFailed=false;return respond(route,{error:{message_code:'network'}},503);}
  return respond(route,{data:{id:91,customer_id:31,plan_id:42,status:'pending_provision',auto_renew:body.auto_renew,used_bytes:0,quota_bytes:5*quota,expires_at:null,entitlement_kind:'paid'}});
 }
 if(path==='/v1/customer/subscriptions/91/renewal-eligibility'){
  if(renewalFailed){renewalFailed=false;return respond(route,{error:{message_code:'network'}},503);}
  return respond(route,{data:{subscription_id:91,renewal_generation:0,checked_at:'2026-10-08T08:00:00Z',auto_renew:true,quote_available:true,eligible:true,reason_code:null,renewal_due:false,auto_renew_authorized:true,payer_kind:renewalOther?'other':'self',wallet_balance_rial:renewalOther?null:101,renewal_price_rial:105,wallet_shortfall_rial:renewalOther?null:4,wallet_funded:renewalOther?null:false}});
 }
 if(path==='/v1/customer/subscriptions/91/delivery')return respond(route,{data:{subscription_id:91,status:'pending_provision',auto_renew:true,portal_url:null,feed_url:null,can_rotate_link:false,entitlement_kind:'paid'}});
 if(path.includes('trial'))return respond(route,{data:{policy:{enabled:false,quota_bytes:1024,duration_days:1},claims:0,eligible:false,reason:'trial_disabled',next_claim_at:null}});
 return respond(route,paged([]));
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/account');
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('button',{name:'خرید سرویس',exact:true}).waitFor();
 await page.getByRole('button',{name:'کیف پول و پرداخت‌ها',exact:true}).waitFor();
 await page.getByRole('heading',{name:'درخواست شارژ کیف پول',exact:true}).waitFor();
 await page.getByRole('heading',{name:'پرداخت‌های من',exact:true}).waitFor();
 await page.getByRole('button',{name:'ایجاد درخواست شارژ',exact:true}).waitFor();
 await page.getByLabel('مبلغ شارژ').fill('0');
 await page.getByRole('button',{name:'ایجاد درخواست شارژ',exact:true}).click();
 await page.getByRole('alert').getByText('مبلغ معتبر وارد کنید.',{exact:true}).waitFor();
 assert.equal(topupWrites.length,0,'Invalid amount reached the payment API');
 await page.getByLabel('مبلغ شارژ').fill('1000');
 await page.getByRole('button',{name:'ایجاد درخواست شارژ',exact:true}).click();
 await page.getByRole('status').getByText('درخواست شارژ ثبت شد. اطلاعات پرداخت و ارسال رسید در ادامه نمایش داده می‌شود.',{exact:true}).waitFor();
 assert.equal(topupWrites.length,1);assert.equal(topupWrites[0].amount_rial,10000);
 await page.getByRole('button',{name:'خرید سرویس',exact:true}).click();
 await page.getByRole('heading',{name:'خرید با کیف پول',exact:true}).waitFor();
 await page.getByRole('heading',{name:'سرویس آزمایشی',exact:true}).waitFor();
 await page.getByLabel('جست‌وجوی پلن').waitFor();
 await page.getByTestId('locale-selector').selectOption('en');
 await page.getByRole('heading',{name:'Trial service',exact:true}).waitFor();
 await page.getByRole('button',{name:'Service purchase',exact:true}).click();
 const loyalty=page.getByRole('region',{name:'Customer loyalty'});
 await loyalty.getByRole('heading',{name:'Silver',exact:true}).waitFor();
 await loyalty.getByRole('heading',{name:'My tier and purchase progress',exact:true}).waitFor();
 assert.match(await loyalty.innerText(),/450 GiB.*next tier/);
 assert.equal(await loyalty.locator('progress').getAttribute('value'),String(250*quota));
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('row').filter({hasText:'Selected volume plan'}).click();
 await page.getByRole('heading',{name:'خرید Selected volume plan',exact:true}).waitFor();
 await page.getByRole('alert').getByText('اتصال به سرور برقرار نشد. دوباره تلاش کنید.',{exact:true}).waitFor();
 await page.getByTestId('locale-selector').selectOption('en');
 await page.getByRole('button',{name:'Retry price quote'}).waitFor();
 assert(await page.getByRole('button',{name:'Confirm wallet purchase'}).isDisabled());
 await page.getByRole('button',{name:'Retry price quote'}).click();
 const priced=page.getByRole('region',{name:'Personalized purchase quote'});await priced.waitFor();
 assert.match(await priced.innerText(),/Wallet charge: 10\.1/);assert.match(await priced.innerText(),/Renewal price under current rules: 10\.5/);
 await page.getByLabel('Renew automatically when my wallet has sufficient funds').check();
 await page.getByRole('button',{name:'Confirm wallet purchase'}).click();await page.getByRole('alert').waitFor();
 assert(await page.getByLabel('Renew automatically when my wallet has sufficient funds').isChecked());
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('button',{name:'تأیید خرید با کیف پول',exact:true}).click();await page.getByRole('heading',{name:'اشتراک 91',exact:true}).waitFor();
 await page.getByRole('status').getByText('خرید شمارهٔ 91 ثبت شد. وضعیت تحویل را در سرویس‌های من پیگیری کنید.',{exact:true}).waitFor();
 await page.getByTestId('locale-selector').selectOption('en');
 const readiness=page.getByRole('region',{name:'Service renewal eligibility'});
 await readiness.getByRole('heading',{name:'Renewal readiness',exact:true}).waitFor();
 await page.getByRole('region',{name:'Subscription source IP allowance'}).getByText('Snapshot unavailable from this API').waitFor();
 await readiness.getByRole('alert').waitFor();assert(!/Automatic renewal is authorized/.test(await readiness.innerText()));
 await readiness.getByRole('button',{name:'Refresh renewal readiness'}).click();await readiness.getByText('My wallet: 10.1 toman').waitFor();
 assert.match(await readiness.innerText(),/Wallet shortfall: 0\.4/);assert.match(await readiness.innerText(),/do not confirm execution/);
 renewalOther=true;await readiness.getByRole('button',{name:'Refresh renewal readiness'}).click();await readiness.getByText('Another payer funds this service. Their wallet details are private.').waitFor();assert(!/My wallet|Wallet shortfall/.test(await readiness.innerText()));
 await page.getByTestId('locale-selector').selectOption('fa');
 const persianReadiness=page.getByRole('region',{name:'شرایط تمدید سرویس'});
 await persianReadiness.getByRole('heading',{name:'آمادگی تمدید',exact:true}).waitFor();
 await page.getByRole('region',{name:'محدودیت IP مبدأ اشتراک'}).getByText('این API تصویری از محدودیت ارائه نکرده است').waitFor();
 await persianReadiness.getByText('پرداخت این سرویس با کیف پول پرداخت‌کنندهٔ دیگری انجام می‌شود. جزئیات کیف پول او خصوصی است.').waitFor();
 assert(!/کیف پول من|کسری کیف پول/.test(await persianReadiness.innerText()));
 await page.getByRole('button',{name:'خرید سرویس',exact:true}).click();
 const persianLoyalty=page.getByRole('region',{name:'وفاداری مشتری'});
 await persianLoyalty.getByRole('heading',{name:'سطح و پیشرفت خرید من',exact:true}).waitFor();
 assert.deepEqual(writes[0],writes[1]);assert.equal(writes[1].plan_id,42);assert.equal(writes[1].auto_renew,true);assert.equal(topupWrites.length,1);assert.equal(topupWrites[0].amount_rial,10000);
 await page.getByTestId('locale-selector').selectOption('en');
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Service purchase',exact:true}).click();await loyalty.getByRole('heading',{name:'Silver',exact:true}).waitFor();
 assert(await loyalty.evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}));assert.deepEqual(errors,[]);
 console.log('Customer tier/progress, own actual quote and renewal price, failed quote purchase fencing, retained purchase retries and mobile passed; controlled HTTP.');
}finally{await browser.close();}
