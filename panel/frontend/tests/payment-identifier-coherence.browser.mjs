// Actual Vue and controlled malformed HTTP responses; no native payment mutations.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],writes=[],outcomes=[];
const topup={id:91,revision:1,customer_id:31,amount_rial:120007,requested_amount_rial:120000,payment_identifier_mode:'rial_suffix4',payment_identifier_code4:'0007',status:'pending',bank_reference:null,approved_by_staff_id:null};
const instruction={destination_id:20,title:'Controlled account',kind:'card',account:'6037990000000001',recipient:'Controlled recipient',bank_name:'Controlled bank',instructions:null,topup_id:91,requested_amount_rial:120000,payable_amount_rial:120007,payment_identifier_mode:'rial_suffix4',payment_identifier_code4:'0007'};
const checkout={id:71,customer_id:31,plan_id:42,revision:1,state:'awaiting_funding',funding_mode:'approved_topup',delivery_mode:'manual_profiles',price_rial:90000,offer_sha256:'a'.repeat(64),auto_renew:false,expires_at:'2026-10-08T10:00:00Z',changed_offer_action:'require_confirmation',topup_id:91,subscription_id:null,reason_code:null};
const cases=[{name:'missing code',patch:{payment_identifier_code4:null}},{name:'code differs from payable suffix',patch:{payment_identifier_code4:'9007'}},{name:'requested amount exceeds payable',patch:{requested_amount_rial:120008}}];
let current=cases[0];
const respond=(r,data)=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)}),paged=data=>({data,meta:{pager:{total_pages:1}}});
page.on('pageerror',e=>errors.push(e.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const req=route.request(),path=new URL(req.url()).pathname.slice(4);
 if(req.method()!=='GET')writes.push(path);
 if(path==='/v1/customer/auth/me')return respond(route,{customer_id:31,display_name:'Controlled customer',csrf_token:'controlled'});
 if(path==='/v1/customer/preferences')return respond(route,{data:{brand_title:'Papilio',topup_options_rial:[],payment_instructions:null,support_handle:null,checkout:{destination_mode:'legacy',allowed_methods:['card'],minimum_topup_rial:10000,maximum_topup_rial:500000},receipts:{enabled:false,max_per_topup:1,allowed_formats:['PNG']}}});
 if(path==='/v1/customer/wallet')return respond(route,{data:{balance_rial:0}});
 if(path==='/v1/customer/checkouts/71')return respond(route,{data:checkout});
 if(path==='/v1/customer/topups/91')return respond(route,{data:{...topup,...current.patch}});
 if(path==='/v1/customer/topups/91/instruction')return respond(route,{data:[{...instruction,...current.patch}]});
 return respond(route,paged([]));
});
async function runCase(candidate){
  current=candidate;await page.goto(process.env.PANEL_ORIGIN+'/account?checkout_id=71');
  const amount=page.getByRole('dialog',{name:'Plan checkout'}).getByRole('region',{name:'Exact payment amount'});await amount.waitFor();
  const transferCount=await amount.getByText(/^Exact transfer amount:/).count(),alertCount=await amount.getByRole('alert').count();
  outcomes.push({name:candidate.name,passed:transferCount===0&&alertCount===1,transferCount,alertCount});
}
try{
 await runCase(cases[0]);
 await runCase(cases[1]);
 await runCase(cases[2]);
 console.log(JSON.stringify({boundary:'controlled malformed HTTP, actual Vue; no native financial claim',outcomes,pageErrors:errors.length,writes:writes.length}));
 assert.deepEqual(errors,[]);assert.equal(writes.length,0);assert(outcomes.every(row=>row.passed),'Malformed coded instruction advertised an exact transfer amount');
}finally{await browser.close();}
