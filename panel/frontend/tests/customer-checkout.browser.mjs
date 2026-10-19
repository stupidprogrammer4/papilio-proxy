// Actual Vue with controlled HTTP. Native payment/worker evidence is separate.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],creates=[],actions=[],destinationPages=[];
let failedCreate=true,failedCancel=true,failedConfirm=true,historyFailed=true,missingExpiry=false;
const plan={id:42,title:'Volume without expiry',code:'volume',price_rial:100000,quota_bytes:5*1024**3,duration_days:null,is_active:true};
let offer={customer_id:31,plan_id:42,price_rial:90000,offer_sha256:'a'.repeat(64),plan_title:plan.title,quota_bytes:plan.quota_bytes,duration_days:null,membership_count:2,delivery_mode:'configured_bundle',captured_at:'2026-10-08T00:00:00Z',default_expiry_seconds:777};
let intent={id:71,customer_id:31,plan_id:42,revision:1,state:'awaiting_funding',funding_mode:'approved_topup',delivery_mode:'configured_bundle',price_rial:90000,offer_sha256:offer.offer_sha256,auto_renew:true,expires_at:'2026-10-08T00:12:57Z',changed_offer_action:'require_confirmation',topup_id:91,subscription_id:null,reason_code:null};
const receipt={id:92,topup_id:91,media_type:'image/jpeg',size_bytes:4096,created_at:'2026-10-08T00:00:00Z',ocr_status:'complete',extraction:{amount_raw:'120000',amount_rial:120000,currency:'rial',destination_kind:null,visible_destination:null,destination_masked:null,bank_namespace:null,bank_reference:null,occurred_at_raw:null,occurred_at_utc:null,calendar:null,timezone:null,transaction_status_claim:null,field_evidence:{amount:{text:'Transfer 120000 rial',confidence_milli:930,line_indexes:[1],region:[]}},warnings:['receipt_image_requires_manual_comparison'],reason_codes:['timezone_unknown']}};
const respond=(r,data,status=200)=>r.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
const paged=(data,total=1)=>({data,meta:{pager:{total_pages:total}}});
page.on('pageerror',e=>errors.push(e.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const req=route.request(),url=new URL(req.url()),path=url.pathname.slice(4);
 if(path==='/v1/customer/auth/me')return respond(route,{customer_id:31,display_name:'Customer',csrf_token:'controlled'});
 if(path==='/v1/customer/wallet')return respond(route,{data:{balance_rial:10000}});
 if(path==='/v1/customer/preferences')return respond(route,{data:{brand_title:'Papilio',topup_options_rial:[],payment_instructions:'Use the selected receiving account',checkout:{destination_mode:'required',minimum_topup_rial:10000,maximum_topup_rial:500000},receipts:{enabled:false}}});
 if(path==='/v1/customer/loyalty')return respond(route,{data:{customer_id:31,purchased_bytes:0,purchase_count:0,lifetime_purchase_count:0,tier:null,next_tier:null}});
 if(path==='/v1/customer/plans')return respond(route,paged([plan]));
 if(path==='/v1/customer/plans/42/quote')return respond(route,{data:{customer_id:31,plan_id:42,price_rial:90000,base_price_rial:100000,discount_rial:10000,renewal_price_rial:95000}});
 if(path.includes('trial'))return respond(route,{data:{policy:{enabled:false,quota_bytes:1024,duration_days:1},claims:0,eligible:false,reason:'trial_disabled',next_claim_at:null}});
 if(path==='/v1/customer/checkouts/offers/42'){const value={...offer};if(missingExpiry)delete value.default_expiry_seconds;return respond(route,{data:value});}
 if(path==='/v1/customer/payment-destinations'){const number=Number(url.searchParams.get('page'));destinationPages.push(number);return respond(route,paged([{destination_id:number===1?10:20,title:number===1?'First account':'Selected bank account',recipient:'Receiving owner',bank_name:'Bank'}],2));}
 if(path==='/v1/customer/checkouts'&&req.method()==='POST'){creates.push(req.postDataJSON());if(failedCreate){failedCreate=false;return respond(route,{error:{message_code:'request_failed'}},503);}return respond(route,{data:intent});}
 if(path==='/v1/customer/checkouts'){if(historyFailed){historyFailed=false;return respond(route,{error:{message_code:'request_failed'}},503);}return respond(route,paged(creates.length?[intent]:[],2));}
 if(path==='/v1/customer/checkouts/71')return respond(route,{data:intent});
 if(path==='/v1/customer/subscriptions/88')return respond(route,{data:{id:88,status:'pending_provision'}});
 if(path==='/v1/customer/subscriptions/88/delivery')return respond(route,{data:{subscription_id:88,status:'pending_provision',feed_url:null,portal_url:null}});
 if(path==='/v1/customer/checkouts/71/cancel'){actions.push({action:'cancel',body:req.postDataJSON()});if(failedCancel){failedCancel=false;return respond(route,{error:{message_code:'request_failed'}},503);}intent={...intent,state:'cancelled',revision:2};return respond(route,{data:intent});}
 if(path==='/v1/customer/checkouts/71/reconfirm'){actions.push({action:'reconfirm',body:req.postDataJSON()});if(failedConfirm){failedConfirm=false;return respond(route,{error:{message_code:'request_failed'}},503);}intent={...intent,state:'ready',price_rial:offer.price_rial,revision:4};return respond(route,{data:intent});}
 if(path==='/v1/customer/topups/91')return respond(route,{data:{id:91,revision:1,customer_id:31,amount_rial:120000,status:'pending',bank_reference:null,approved_by_staff_id:null}});
 if(path==='/v1/customer/topups/91/instruction')return respond(route,{data:[{title:'Selected receiving account',bank_name:'Bank',recipient:'Receiving owner',account:'controlled',instructions:'Transfer the requested amount'}]});
 if(path==='/v1/customer/topups/91/receipts')return respond(route,paged([receipt]));
 return respond(route,paged([]));
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/account');
 await page.getByRole('button',{name:'Service purchase',exact:true}).click();
 const history=page.getByRole('region',{name:'Checkout history'});
 await history.getByText('Checkouts could not be loaded. Retry to view saved purchases.').waitFor();
 await history.getByRole('button',{name:'Refresh checkouts'}).click();await history.getByText('No checkouts yet.',{exact:true}).waitFor();
 await page.getByRole('row').filter({hasText:plan.title}).click();
 await page.getByRole('button',{name:'Automated checkout',exact:true}).click();
 const initialDialog=page.getByRole('dialog');await initialDialog.getByRole('heading',{name:plan.title}).waitFor();
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('dialog',{name:'پرداخت خرید پلن'}).waitFor();
 await page.getByTestId('locale-selector').selectOption('en');
 const dialog=page.getByRole('dialog',{name:'Plan checkout'});
 await dialog.getByLabel('Purchase funding').selectOption('approved_topup');
 await dialog.getByLabel('Requested wallet top-up (toman)').fill('12000');
 await dialog.getByRole('button',{name:'Next destinations'}).click();
 await dialog.getByRole('button',{name:'Selected bank account · Bank',exact:true}).click();
 await dialog.getByRole('button',{name:'Previous destinations'}).click();
 await dialog.getByText('Selected: Selected bank account · Receiving owner').waitFor();
 await dialog.getByLabel('Renew automatically when my wallet has sufficient funds').check();
 await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).click();await dialog.getByRole('alert').waitFor();
 assert.equal(await dialog.getByLabel('Purchase funding').isDisabled(),true);
 assert.equal(await dialog.getByRole('button',{name:'Close dialog'}).isDisabled(),true);
 await dialog.getByRole('button',{name:'Retry same checkout',exact:true}).click();await dialog.getByRole('heading',{name:'Checkout #71'}).waitFor();
 assert.deepEqual(creates[0],creates[1]);assert.equal(creates[1].plan_id,42);assert.equal(creates[1].expiry_seconds,777);assert.equal(creates[1].destination_id,20);assert.equal(creates[1].topup_amount_rial,120000);assert.equal(creates[1].expected_price_rial,90000);assert.equal(creates[1].auto_renew,true);
 await dialog.getByText('Selected receiving account · Bank',{exact:true}).waitFor();
 await dialog.getByText('Some receipt fields are missing or ambiguous. Review the image before taking action.',{exact:true}).waitFor();
 assert.equal(await dialog.getByTestId('ocr-reason-codes').count(),0);
 assert.equal(await dialog.getByTestId('ocr-warnings').count(),0);
 assert.equal(await dialog.getByTestId('ocr-field-evidence').count(),0);
 await dialog.getByRole('button',{name:'Cancel checkout',exact:true}).click();await dialog.getByRole('button',{name:'Retry cancellation'}).waitFor();
 await dialog.getByRole('button',{name:'Retry cancellation'}).click();await dialog.locator('p[role="status"]').getByText('Cancelled',{exact:true}).waitFor();
 assert.deepEqual(actions[0],actions[1]);assert.equal(actions[1].body.expected_revision,1);
 assert.match(await dialog.innerText(),/approved payment remains in your wallet/);
 await dialog.getByRole('button',{name:'Close dialog'}).click();
 intent={...intent,state:'action_required',revision:3,reason_code:'checkout_offer_changed'};offer={...offer,price_rial:95000,offer_sha256:'b'.repeat(64)};
 await page.reload();await dialog.locator('p[role="status"]').getByText('Review required',{exact:true}).waitFor();await dialog.getByRole('list',{name:'Payment-to-delivery progress'}).locator('li[data-stage="funding"]').getByText('Review required',{exact:true}).waitFor();
 await dialog.getByRole('button',{name:'Confirm updated offer'}).click();await dialog.getByRole('button',{name:'Retry confirmation'}).waitFor();
 await dialog.getByRole('button',{name:'Retry confirmation'}).click();await dialog.locator('p[role="status"]').getByText('Ready for purchase processing',{exact:true}).waitFor();
 assert.deepEqual(actions[2],actions[3]);assert.equal(actions[3].body.expected_revision,3);assert.equal(actions[3].body.expected_price_rial,95000);assert.equal(actions[3].body.expected_offer_sha256,'b'.repeat(64));
 await page.setViewportSize({width:390,height:844});assert(await dialog.evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}));
 assert(destinationPages.includes(2));assert.deepEqual(errors,[]);
 await dialog.getByRole('button',{name:'Close dialog'}).click();
 await page.goto(process.env.PANEL_ORIGIN+'/account');await page.getByRole('button',{name:'Service purchase',exact:true}).click();await page.getByRole('row').filter({hasText:plan.title}).click();missingExpiry=true;
 await page.getByRole('button',{name:'Automated checkout',exact:true}).click();await dialog.getByRole('heading',{name:plan.title}).waitFor();
 assert.equal(await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).isDisabled(),true);
 intent={...intent,state:'purchased',subscription_id:88};
 await page.goto(process.env.PANEL_ORIGIN+'/account?checkout_id=71');
 const completed=page.getByRole('dialog',{name:'Plan checkout'});
 await completed.getByRole('heading',{name:'Checkout #71'}).waitFor();
 await completed.getByLabel('Payment-to-delivery progress').getByText('Purchase recorded',{exact:true}).waitFor();
 await completed.getByLabel('Payment-to-delivery progress').locator('li[data-stage="delivery"]').getByText('Pending provisioning',{exact:true}).waitFor();
 await completed.getByRole('link',{name:'View purchased service'}).waitFor();
 console.log('Owned checkout modal, configured expiry, paged destination retention, exact create/action retries, payment context, cancellation, changed offer, durable URL resume and mobile passed; controlled HTTP.');
}finally{await browser.close();}
