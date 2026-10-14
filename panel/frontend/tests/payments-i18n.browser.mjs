// Actual Payments Vue flow with controlled, read-only HTTP responses.
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage({viewport:{width:1440,height:1080}}),errors=[];
page.setDefaultTimeout(8000);
page.on('pageerror',error=>errors.push(error.message));
const sms={id:101,event_id:'controlled-sms',device_id:null,sender:'Controlled bank',amount_rial:100000,balance_rial:900000,bank_reference:'controlled-ref',sent_at:'2026-10-08T00:00:00Z',direction:'credit',parser_revision_id:null,parser_definition_sha256:null,receiving_realm_id:null,receiving_alias_id:null,captured_destination_id:null,captured_destination_revision:null,parse_reason_code:null,origin_reason_code:null,origin_kind:'direct_sms',original_provider_timestamp_ms:null,canonicalization_revision:null,declared_notification_sha256:null,canonical_message_digest:null,origin_identity_sha256:null};
const topup={id:700,customer_id:42,amount_rial:100000,requested_amount_rial:100000,status:'pending',bank_reference:null,payment_identifier_mode:'exact_requested',payment_identifier_code4:null,created_at:'2026-10-08T00:00:00Z'};
const capabilities={supported:true,configured:false,read_available:true,enabled:false,capacity:{page_size:20,max_page_size:20,max_profiles:20,max_profile_bytes:200000,max_rules_per_field:20,max_marker_chars:200,max_clauses:50,max_message_bytes:4000,max_realms:20,max_aliases_per_realm:20,max_match_candidates:20},parser_modes:[],identity_modes:[],amount_relations:[],units:[],required_origin_fields:[],canonicalization_revision:1,source_assurance:'enrolled_sender_declared_metadata',bank_settlement_verified:false};
const review={sms_event_id:101,device_id:null,device_revision:null,receiving_realm_id:null,realm_revision:null,destination_id:null,destination_revision:null,status:'manual',reason_code:'sms_source_unverified',checked_at:null,candidate_count:0,topup_id:null,settlement_id:null,evidence_kind:null,manual_approval_available:false};
const paged=data=>({data,meta:{pager:{total_items:data.length,total_pages:1,current_page:1,per_page:20,has_prev:false,has_next:false}}});
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const path=new URL(route.request().url()).pathname.slice(4);
 assert.equal(route.request().method(),'GET','Locale review must not mutate payment state');
 let body=paged([]);
 if(path==='/v1/admin/auth/me')body={username:'controlled-payments',scopes:['*'],csrf_token:'controlled'};
 else if(path==='/v1/admin/preferences')body={data:{revision:0,values:{brand_title:'Papilio'}}};
 else if(path==='/v1/admin/payments/topups')body=paged([topup]);
 else if(path==='/v1/admin/payments/topups/700/instruction')body={data:[]};
 else if(path==='/v1/admin/payments/topups/700/receipts')body=paged([]);
 else if(path==='/v1/admin/payments/sms')body=paged([sms]);
 else if(path==='/v1/admin/payments/sms/101')body={data:sms};
 else if(path==='/v1/admin/payments/sms-origins/capabilities')body={data:capabilities};
 else if(path==='/v1/admin/payments/sms-origins/sms-events/101/review')body={data:review};
 return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
});
try{
 await page.goto(`${process.env.PANEL_ORIGIN}/payments`);
 await mkdir('.local-review/appearance',{recursive:true});
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('heading',{name:'پرداخت‌ها',exact:true}).waitFor();
 await page.getByRole('heading',{name:'بررسی پرداخت',exact:true}).waitFor();
 await page.getByRole('row').filter({hasText:'700'}).click();
 await page.getByRole('heading',{name:/دستور پرداخت و رسیدها/}).waitFor();
 await page.getByText('مبلغ دقیق انتقال', {exact:false}).waitFor();
 await page.getByText(/تومان/).first().waitFor();
 await page.getByRole('button',{name:'بررسی پیامک',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'مشاهدهٔ پیامک',exact:true});
 await dialog.getByText('بررسی تسویه', {exact:true}).waitFor();
 await dialog.getByText('مبلغ واریز', {exact:true}).waitFor();
 await dialog.getByText(/۱۴۰۵/).waitFor();
 await page.screenshot({path:'.local-review/appearance/payments-sms-review-fa.png',animations:'disabled'});
 assert.deepEqual(errors,[]);
 console.log('PASS: payment review and captured SMS settlement view render in Persian; controlled read-only HTTP');
}finally{await browser.close();}
