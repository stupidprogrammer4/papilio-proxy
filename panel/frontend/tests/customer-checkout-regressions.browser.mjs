// Actual Vue, independent scenarios, controlled API HTTP; no native money claims.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const outcomes = [];
const origin = process.env.PANEL_ORIGIN;
const plan = {id:42,title:'Current plan',code:'current',price_rial:100000,quota_bytes:5*1024**3,duration_days:30,is_active:true};
const offer = {customer_id:31,plan_id:42,price_rial:90000,offer_sha256:'a'.repeat(64),plan_title:plan.title,quota_bytes:plan.quota_bytes,duration_days:30,membership_count:2,delivery_mode:'configured_bundle',captured_at:'2026-10-08T00:00:00Z',default_expiry_seconds:777};
const original = {id:71,customer_id:31,plan_id:42,revision:1,state:'ready',funding_mode:'wallet_only',delivery_mode:'configured_bundle',price_rial:90000,offer_sha256:offer.offer_sha256,auto_renew:false,expires_at:'2026-10-09T00:12:57Z',changed_offer_action:'require_confirmation',topup_id:null,subscription_id:null,reason_code:null};
const paged = data => ({data,meta:{pager:{total_pages:1}}});
const respond = (route,data,status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});

async function scenario(name,run){
 const context = await browser.newContext();
 const page = await context.newPage();
 page.setDefaultTimeout(5000);
 const state={intent:{...original},offer:{...offer},creates:[],actions:[],errors:[],extra:null};
 page.on('pageerror',cause=>state.errors.push(cause.message));
 await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.slice(4);
  if(state.extra && await state.extra(route,path,request))return;
  if(path==='/v1/customer/auth/me')return respond(route,{customer_id:31,display_name:'Controlled customer',csrf_token:'controlled'});
  if(path==='/v1/customer/wallet')return respond(route,{data:{balance_rial:2000000}});
  if(path==='/v1/customer/preferences')return respond(route,{data:{brand_title:'Controlled',topup_options_rial:[],payment_instructions:null,checkout:{destination_mode:'legacy',minimum_topup_rial:100,maximum_topup_rial:2000000,allowed_methods:['card']},receipts:{enabled:false}}});
  if(path==='/v1/customer/plans')return respond(route,paged([plan]));
  if(path==='/v1/customer/plans/42/quote')return respond(route,{data:{customer_id:31,plan_id:42,price_rial:90000,base_price_rial:100000,discount_rial:10000,renewal_price_rial:95000}});
  if(path==='/v1/customer/checkouts/offers/42')return respond(route,{data:state.offer});
  if(path==='/v1/customer/checkouts' && request.method()==='POST'){
   state.creates.push(request.postDataJSON());return respond(route,{data:state.intent});
  }
  if(path==='/v1/customer/checkouts')return respond(route,paged([state.intent]));
  if(/^\/v1\/customer\/checkouts\/\d+$/.test(path))return respond(route,{data:{...state.intent,id:Number(path.split('/').at(-1))}});
  if(path==='/v1/customer/checkouts/71/reconfirm'){
   state.actions.push(request.postDataJSON());return respond(route,{data:state.intent});
  }
  if(path==='/v1/customer/loyalty')return respond(route,{data:{customer_id:31,purchased_bytes:0,purchase_count:0,lifetime_purchase_count:0,tier:null,next_tier:null}});
  if(path.includes('trial'))return respond(route,{data:{policy:{enabled:false,quota_bytes:1024,duration_days:1},claims:0,eligible:false,reason:'trial_disabled',next_claim_at:null}});
  return respond(route,paged([]));
 });
 try{await run(page,state);assert.deepEqual(state.errors,[]);outcomes.push({name,passed:true});}
 catch(cause){outcomes.push({name,passed:false,error:cause.message});}
 finally{await context.close();}
}
async function newCheckout(page){
 await page.goto(origin+'/account');
 await page.getByRole('button',{name:'Service purchase',exact:true}).click();
 await page.getByRole('row').filter({hasText:plan.title}).click();
 await page.getByRole('button',{name:'Automated checkout',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Plan checkout'});
 await dialog.getByRole('heading',{name:plan.title}).waitFor();return dialog;
}
async function routeQuery(page,query){
 await page.evaluate(query=>{
  const current='/account'+query;
  history.pushState({...history.state,back:location.pathname+location.search,current,forward:null,position:(history.state?.position??0)+1},'',current);
  dispatchEvent(new PopStateEvent('popstate',{state:history.state}));
 },query);
}
try{
 await scenario('uncertain create followed by 429 retains identical key and body',async(page,state)=>{
  state.extra=async(route,path,request)=>{
   if(path!=='/v1/customer/checkouts'||request.method()!=='POST')return false;
   state.creates.push(request.postDataJSON());
   const count=state.creates.length;
   if(count<=2)await respond(route,{error:{message_code:'request_failed'}},count===1?503:429);
   else await respond(route,{data:state.intent});return true;
  };
  const dialog=await newCheckout(page);
  await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).click();
  await dialog.getByRole('button',{name:'Retry same checkout',exact:true}).waitFor();
  await dialog.getByRole('button',{name:'Retry same checkout',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="alert"]')!==null);
  const retry=dialog.getByRole('button',{name:/^(Retry same checkout|Confirm checkout)$/});
  await retry.click();await dialog.getByRole('heading',{name:'Checkout #71'}).waitFor();
  assert.equal(state.creates.length,3);
  assert.deepEqual(state.creates[2],state.creates[0],'429 discarded the unresolved key/body');
 });
 await scenario('fractional toman input sends exact integer rial',async(page,state)=>{
  const dialog=await newCheckout(page);
  await dialog.getByLabel('Purchase funding').selectOption('approved_topup');
  await dialog.getByLabel('Requested wallet top-up (toman)').fill('12000.5');
  await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).click();
  await dialog.getByRole('heading',{name:'Checkout #71'}).waitFor();
  assert.equal(state.creates[0].topup_amount_rial,120005,'fractional toman was silently transformed');
 });
 await scenario('uncertain reconfirm remains resolvable after ready refresh',async(page,state)=>{
  state.intent={...original,state:'action_required',revision:3};
  state.extra=async(route,path,request)=>{
   if(path!=='/v1/customer/checkouts/71/reconfirm')return false;
   state.actions.push(request.postDataJSON());
   state.intent={...state.intent,state:'ready',revision:4};
   await respond(route,state.actions.length===1?{error:{message_code:'request_failed'}}:{data:state.intent},state.actions.length===1?503:200);return true;
  };
  await page.goto(origin+'/account?checkout_id=71');
  const dialog=page.getByRole('dialog',{name:'Plan checkout'});
  await dialog.getByRole('button',{name:'Confirm updated offer',exact:true}).click();
  await dialog.getByRole('button',{name:'Retry confirmation',exact:true}).waitFor();
  await dialog.getByRole('button',{name:'Refresh checkout',exact:true}).click();
  await dialog.getByText('Ready for purchase processing',{exact:true}).waitFor();
  const resolver=dialog.getByRole('button',{name:/Retry.*confirmation|Resolve.*confirmation/i});
  assert.equal(await resolver.count(),1,'refresh hid the only retained confirmation resolver');
  await resolver.click();assert.deepEqual(state.actions[1],state.actions[0]);
 });
 await scenario('changed offer shows quota duration and delivery mode before reconfirm',async(page,state)=>{
  state.intent={...original,state:'action_required',revision:3};
  state.offer={...offer,quota_bytes:2*1024**3,duration_days:7,delivery_mode:'manual_profiles'};
  await page.goto(origin+'/account?checkout_id=71');
  const dialog=page.getByRole('dialog',{name:'Plan checkout'});
  await dialog.getByRole('button',{name:'Confirm updated offer',exact:true}).waitFor();
  const text=await dialog.innerText();
  const missing=[['quota',/2 GiB/],['duration',/7 days/],['delivery mode',/manual/i]].filter(([,pattern])=>!pattern.test(text)).map(([name])=>name);
  assert.deepEqual(missing,[],'current offer terms absent from review');
 });
 await scenario('browser Back clears removed checkout route identity',async(page)=>{
  await page.goto(origin+'/account');
  await page.getByRole('heading',{name:'Controlled customer',exact:true}).waitFor();
  await routeQuery(page,'?checkout_id=71');
  const dialog=page.getByRole('dialog',{name:'Plan checkout'});
  await dialog.getByRole('heading',{name:'Checkout #71'}).waitFor();
  await page.goBack();await page.waitForURL(origin+'/account');
  await page.waitForFunction(()=>document.querySelector('dialog[open]')===null);
  assert.equal(await dialog.isVisible(),false,'route no longer owns a checkout but old modal remains open');
 });
 await scenario('late prior-identity response cannot replace current selected checkout',async(page,state)=>{
  let release;
  const held=new Promise(resolve=>{release=resolve;});
  let started;
  const startedPromise=new Promise(resolve=>{started=resolve;});
  state.extra=async(route,path)=>{
   if(path!=='/v1/customer/checkouts/72')return false;
   started();await held;await respond(route,{data:{...original,id:72}});return true;
  };
  await page.goto(origin+'/account?checkout_id=71');
  const dialog=page.getByRole('dialog',{name:'Plan checkout'});
  await dialog.getByRole('heading',{name:'Checkout #71'}).waitFor();
  await routeQuery(page,'?checkout_id=72');await Promise.race([startedPromise,new Promise((_,reject)=>setTimeout(()=>reject(new Error('prior identity read did not begin')),5000))]);
  await routeQuery(page,'?checkout_id=73');
  await dialog.getByRole('heading',{name:'Checkout #73'}).waitFor();
  release();await page.waitForResponse(response=>response.url().endsWith('/v1/customer/checkouts/72'));
  assert.equal(await dialog.getByRole('heading',{name:'Checkout #73'}).count(),1);
  assert.equal(await dialog.getByRole('heading',{name:'Checkout #72'}).count(),0);
 });
 await scenario('unknown cancellation retains original key and fences create retry',async(page,state)=>{
  const retires=[];
  state.extra=async(route,path,request)=>{
   if(path==='/v1/customer/checkouts'&&request.method()==='POST'){
    state.creates.push(request.postDataJSON());await respond(route,{error:{message_code:'request_failed'}},503);return true;
   }
   if(path==='/v1/customer/checkouts/retire'){
    retires.push(request.postDataJSON());
    await respond(route,retires.length===1?{error:{message_code:'request_failed'}}:{data:{request_key:retires[0].request_key,status:'retired',intent:null}},retires.length===1?503:200);return true;
   }
   return false;
  };
  const dialog=await newCheckout(page);
  await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).click();
  await dialog.getByRole('button',{name:'Cancel unresolved request',exact:true}).click();
  const retry=dialog.getByRole('button',{name:'Retry cancellation',exact:true});
  await retry.waitFor();
  assert.equal(await dialog.getByRole('button',{name:'Retry same checkout',exact:true}).isDisabled(),true);
  assert.deepEqual(retires[0],{request_key:state.creates[0].request_key});
  await retry.click();
  await dialog.getByText('This request is cancelled.',{exact:false}).waitFor();
  assert.deepEqual(retires[1],retires[0]);
  assert.equal(state.creates.length,1);
  assert.equal(await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).isEnabled(),true);
  await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).click();
  await dialog.getByRole('button',{name:'Retry same checkout',exact:true}).waitFor();
  assert.notEqual(state.creates[1].request_key,state.creates[0].request_key);
 });
 await scenario('retirement preserves a purchase that already committed',async(page,state)=>{
  state.extra=async(route,path,request)=>{
   if(path==='/v1/customer/checkouts'&&request.method()==='POST'){
    state.creates.push(request.postDataJSON());await respond(route,{error:{message_code:'request_failed'}},503);return true;
   }
   if(path==='/v1/customer/checkouts/retire'){
    const body=request.postDataJSON();
    await respond(route,{data:{request_key:body.request_key,status:'purchased',intent:{...original,state:'purchased',subscription_id:88}}});return true;
   }
   return false;
  };
  const dialog=await newCheckout(page);
  await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).click();
  await dialog.getByRole('button',{name:'Cancel unresolved request',exact:true}).click();
  await dialog.getByRole('heading',{name:'Checkout #71'}).waitFor();
  await dialog.getByText('The purchase already completed.',{exact:false}).waitFor();
  assert.equal(await dialog.getByRole('link',{name:'View purchased service'}).getAttribute('href'),'/account?subscription_id=88');
  assert.equal(state.creates.length,1);
 });
 async function contradictoryRetirement(page,state,status,intent){
  state.extra=async(route,path,request)=>{
   if(path==='/v1/customer/checkouts'&&request.method()==='POST'){
    state.creates.push(request.postDataJSON());await respond(route,{error:{message_code:'request_failed'}},503);return true;
   }
   if(path==='/v1/customer/checkouts/retire'){
    await respond(route,{data:{request_key:request.postDataJSON().request_key,status,intent}});return true;
   }
   return false;
  };
  const dialog=await newCheckout(page);
  await dialog.getByRole('button',{name:'Confirm checkout',exact:true}).click();
  await dialog.getByRole('button',{name:'Cancel unresolved request',exact:true}).click();
  await dialog.getByRole('button',{name:'Retry cancellation',exact:true}).waitFor();
  assert.equal(await dialog.getByRole('button',{name:'Retry same checkout',exact:true}).isDisabled(),true);
  assert.equal(await dialog.getByRole('heading',{name:'Checkout #71'}).count(),0);
  assert.equal(state.creates.length,1);
 }
 await scenario('contradictory purchased retirement cannot clear unknown request',async(page,state)=>{
  await contradictoryRetirement(page,state,'purchased',{...original});
 });
 await scenario('contradictory retired retirement cannot announce cancellation',async(page,state)=>{
  await contradictoryRetirement(page,state,'retired',{...original,state:'purchased',subscription_id:88});
 });
 console.log(JSON.stringify({boundary:'actual Vue / controlled API HTTP',outcomes},null,2));
 assert.equal(outcomes.filter(row=>!row.passed).length,0,'checkout consumer regression scenarios failed');
}finally{await browser.close();}
