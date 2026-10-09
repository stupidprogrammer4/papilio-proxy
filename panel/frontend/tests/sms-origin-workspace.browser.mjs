// Controlled external HTTP with the actual Vue app; native settlement and parser gates are separate.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],writes=[],reads=[];
let support='legacy',scope=['payments:read','payments:update'],bindingAttempt=0;
const capacity={enabled:true,page_size:1,max_page_size:20,max_profiles:50,max_profile_bytes:200000,max_rules_per_field:20,max_marker_chars:200,max_clauses:50,max_message_bytes:4000,max_realms:50,max_aliases_per_realm:20,max_match_candidates:20,original_timestamp_future_seconds:60,original_timestamp_max_age_seconds:86400};
const caps=()=>({supported:true,configured:support!=='disabled',read_available:true,enabled:support==='enabled',capacity:support==='disabled'?null:capacity,parser_modes:['legacy_strict_reference','labelled_credit'],identity_modes:['bank_reference_required','trusted_origin_fingerprint'],amount_relations:['label_before_amount','amount_before_label'],units:['rial','toman'],required_origin_fields:['kind','original_provider_timestamp_ms','original_sender','canonicalization_revision'],canonicalization_revision:1,source_assurance:'enrolled_sender_declared_metadata',bank_settlement_verified:false});
const definition={mode:'labelled_credit',credit_markers:['Synthetic credit'],debit_markers:['Synthetic debit'],clause_separators:['\n'],deposit_relations:[{marker:'Synthetic deposit',relation:'label_before_amount',implicit_unit:null}],balance_relations:[{marker:'Synthetic balance',relation:'label_before_amount',implicit_unit:null}],reference_labels:['Synthetic reference'],rial_labels:['rial'],toman_labels:['toman'],grouping_separators:[','],case_sensitive:false};
let destination={destination_id:61,title:'Controlled saved destination',kind:'card',account:'0000000000000061',recipient:'Controlled fixture',bank_name:'Controlled bank',instructions:null,is_active:true,revision:3,receiving_alias_id:null};
let realm={id:70,realm_key:'00000000-0000-4000-8000-000000000070',title:'Controlled receiving account 70',is_active:true,revision:4,origin_mode_enabled:true,origin_requirement_since_ms:1791417600000,created_at:'2026-10-08T00:00:00Z'};
let device={id:87,label:'Controlled SMS sender',senders:['Controlled bank'],is_active:true,revision:3,expires_at:'2027-10-08T00:00:00Z',approval_mode:'unique_sms',destination_id:61,parser_profile_id:92,settlement_identity_mode:'trusted_origin_fingerprint'};
const profile=id=>({id,title:'Controlled parser '+id,is_active:true,revision:2,current_parser_revision_id:id+100,created_at:'2026-10-08T00:00:00Z'});
const revision=(id,version)=>({id:id+100+version,profile_id:id,revision:version,definition_sha256:'a'.repeat(64),definition,created_by_staff_id:5,created_at:'2026-10-08T00:00:00Z'});
const alias=id=>({id,realm_id:70,kind:'card',account_sha256:'c'.repeat(64),bank_namespace:null,created_at:'2026-10-08T00:00:00Z'});
const sms={id:101,event_id:'controlled-event-101',device_id:87,sender:'Controlled bank',amount_rial:100000,balance_rial:900000,bank_reference:null,sent_at:'2026-10-08T00:00:00Z',direction:'credit',parser_revision_id:194,parser_definition_sha256:'a'.repeat(64),receiving_realm_id:70,receiving_alias_id:79,captured_destination_id:61,captured_destination_revision:3,parse_reason_code:null,origin_kind:'direct_sms',original_provider_timestamp_ms:1791417600000,canonicalization_revision:1,canonical_message_digest:'b'.repeat(64),origin_identity_sha256:'c'.repeat(64)};
function respond(route,data,status=200){return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});}
const paged=(data,total=1)=>({data,meta:{pager:{total_pages:total,total_items:data.length}}});
async function install(target){target.on('pageerror',error=>errors.push(error.message));await target.route(url=>url.pathname.startsWith('/api/'),route=>{
 const req=route.request(),url=new URL(req.url()),path=url.pathname.slice(4),method=req.method(),number=Number(url.searchParams.get('page')||1);
 if(method==='GET')reads.push(path);else writes.push({path,body:req.postDataJSON()});
 if(path==='/v1/admin/auth/me')return respond(route,{username:'controlled-sms',scopes:scope,csrf_token:'controlled-csrf'});
 if(path==='/v1/admin/preferences')return respond(route,{data:{revision:0,values:{brand_title:'Papilio'}}});
 const base='/v1/admin/payments/sms-origins';
 if(path===base+'/capabilities')return support==='legacy'?respond(route,{error:{message_code:'not_found'}},404):respond(route,{data:caps()});
 if(path==='/v1/admin/payments/destinations/61')return respond(route,{data:destination});
 if(path==='/v1/admin/payments/destinations')return respond(route,paged([destination]));
 if(path===base+'/receiving-realms')return respond(route,paged([number===2?realm:{...realm,id:71,title:'Other controlled account',realm_key:'00000000-0000-4000-8000-000000000071'}],2));
 if(path===base+'/receiving-realms/70')return respond(route,{data:realm});
 if(path===base+'/receiving-realms/70/aliases')return respond(route,paged([alias(number===2?80:79)],2));
 if(path===base+'/aliases/79')return respond(route,{data:alias(79)});
 if(path===base+'/destinations/61/receiving-account'){
  bindingAttempt++;if(bindingAttempt===1)return respond(route,{error:{message_code:'controlled_outage'}},503);
  if(bindingAttempt===2){destination={...destination,revision:4};realm={...realm,revision:5};return respond(route,{error:{message_code:'sms_receiving_realm_revision_conflict'}},409);}
  assert.deepEqual(req.postDataJSON(),{realm_id:70,expected_destination_revision:4,expected_realm_revision:5,bank_namespace:null});destination={...destination,revision:5,receiving_alias_id:79};return respond(route,{data:destination});
 }
 if(path===base+'/parser-profiles')return respond(route,paged([profile(number===2?92:91)],2));
 if(path===base+'/parser-profiles/91'||path===base+'/parser-profiles/92')return respond(route,{data:profile(Number(path.split('/').at(-1)))});
 if(path===base+'/parser-profiles/91/revisions')return respond(route,paged([revision(91,number===2?1:2)],2));
 if(path===base+'/parser-profiles/91/revisions/2')return respond(route,{data:revision(91,2)});
 if(path===base+'/parser-profiles/91/revisions/2/sample'){assert.deepEqual(req.postDataJSON(),{deposit_relation_index:0,deposit_rial:100000,balance_relation_index:0,balance_rial:900000,unit:'rial',bank_reference:null});return respond(route,{data:{generated_message:'Controlled synthetic deposit 100000 rial\nControlled balance 900000 rial',direction:'credit',deposit_rial:100000,balance_rial:900000,bank_reference:null,reason_code:null,parser_revision_id:193,definition_sha256:'a'.repeat(64),settlement_eligible:false}});}
 if(path==='/v1/admin/payments/sms-devices/87'&&method==='PUT'){const body=req.postDataJSON();assert.equal(body.parser_profile_id,92);assert.equal(body.settlement_identity_mode,'trusted_origin_fingerprint');assert.equal(body.is_active,false);assert.equal(body.expected_revision,3);device={...device,...body,revision:4};return respond(route,{data:device});}
 if(path==='/v1/admin/payments/sms-devices/87')return respond(route,{data:device});
 if(path==='/v1/admin/payments/sms-devices')return respond(route,paged([device]));
 if(path==='/v1/admin/payments/sms/101')return respond(route,{data:sms});
 if(path==='/v1/admin/payments/sms')return respond(route,paged([sms]));
 return respond(route,paged([]));
 });}
try{
 await install(page);await page.goto(process.env.PANEL_ORIGIN+'/payments');
 await page.getByText('SMS parser and source-identity management is unavailable. Existing payment review remains available.',{exact:true}).waitFor();
 assert.equal(reads.filter(path=>path.includes('/parser-profiles')).length,0);
 support='disabled';await page.getByRole('button',{name:'Refresh capabilities'}).click();
 await page.getByText('SMS parser and source-identity management is disabled in the current operational policy. Existing payment review remains available.',{exact:true}).waitFor();
 await page.getByText('Controlled parser 91',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Create parser profile',exact:true}).count(),0);
 await page.getByRole('button',{name:'Open profile',exact:true}).click();let dialog=page.getByRole('dialog',{name:'Parser profile: Controlled parser 91'});await dialog.getByLabel('Profile title').waitFor();assert(await dialog.getByRole('button',{name:'Save new immutable revision'}).isDisabled());await dialog.getByRole('button',{name:'Close dialog'}).click();
 support='enabled';await page.getByRole('button',{name:'Refresh capabilities'}).click();await page.getByRole('button',{name:'Bind receiving account',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'Bind receiving account'});await dialog.getByText('Other controlled account',{exact:true}).waitFor();await dialog.getByRole('button',{name:'›',exact:true}).click();await dialog.getByText('Controlled receiving account 70',{exact:true}).waitFor();await dialog.getByRole('button',{name:'Select',exact:true}).click();await dialog.getByRole('button',{name:'‹',exact:true}).click();await dialog.getByText('Other controlled account',{exact:true}).waitFor();assert.match(await dialog.innerText(),/Selected receiving account: Controlled receiving account 70/);
 await dialog.getByRole('button',{name:'Bind saved destination'}).click();await dialog.getByRole('alert').waitFor();assert.match(await dialog.innerText(),/Controlled receiving account 70/);
 await dialog.getByRole('button',{name:'Bind saved destination'}).click();await dialog.getByText('This receiving account changed. Check its current revision; your draft is retained.',{exact:true}).waitFor();assert.deepEqual(writes[0],writes[1]);
 await dialog.getByRole('button',{name:'Check saved revisions; retain selection'}).click();await dialog.getByRole('button',{name:'Use reviewed current records'}).click();await dialog.getByRole('button',{name:'Bind saved destination'}).click();await dialog.waitFor({state:'hidden'});
 await page.getByRole('button',{name:'Open profile',exact:true}).click();dialog=page.getByRole('dialog',{name:'Parser profile: Controlled parser 91'});await dialog.getByLabel('Generated deposit (rial)').fill('100000');await dialog.getByRole('combobox',{name:/^Balance rule/}).selectOption('0');await dialog.getByLabel('Generated balance (rial)').fill('900000');await dialog.getByRole('button',{name:'Generate parser preview'}).click();await dialog.getByText('Parser preview only · Not eligible for settlement',{exact:true}).waitFor();assert.equal(await dialog.getByRole('button',{name:/Approve/}).count(),0);await dialog.getByRole('button',{name:'Close dialog'}).click();
 const accounts=page.locator('.record-section').filter({has:page.getByRole('heading',{name:'Receiving accounts',exact:true})});await accounts.getByRole('button',{name:'›',exact:true}).click();await accounts.getByText('Controlled receiving account 70',{exact:true}).waitFor();await accounts.getByRole('button',{name:'Open account'}).click();dialog=page.getByRole('dialog',{name:'Receiving account: Controlled receiving account 70'});const aliases=dialog.getByRole('region',{name:'Receiving account aliases'});await aliases.getByText('#79',{exact:true}).waitFor();await aliases.getByRole('button',{name:'›',exact:true}).click();await aliases.getByText('#80',{exact:true}).waitFor();assert.equal(await aliases.getByText(destination.account,{exact:true}).count(),0);await dialog.getByRole('button',{name:'Close dialog'}).click();
 await page.getByRole('row').filter({has:page.getByText('Controlled SMS sender',{exact:true})}).click();await page.getByRole('button',{name:'Edit device',exact:true}).click();dialog=page.getByRole('dialog',{name:'Edit SMS device'});await dialog.getByText('Controlled parser 91',{exact:true}).waitFor();const parserSelection=dialog.locator('section.form-grid');await parserSelection.getByRole('button',{name:'›',exact:true}).click();await parserSelection.getByText('Controlled parser 92',{exact:true}).waitFor();await parserSelection.getByRole('button',{name:'Selected',exact:true}).click();await parserSelection.getByRole('button',{name:'‹',exact:true}).click();await parserSelection.getByText('Controlled parser 91',{exact:true}).waitFor();assert.match(await parserSelection.innerText(),/Selected parser profile: Profile #92/);await dialog.getByRole('button',{name:'Close dialog'}).click();
 await page.getByRole('button',{name:'Revoke device',exact:true}).click();dialog=page.getByRole('dialog',{name:'Revoke SMS device'});await dialog.getByRole('button',{name:'Revoke device',exact:true}).click();await dialog.waitFor({state:'hidden'});
 await page.getByRole('button',{name:'Inspect SMS',exact:true}).click();dialog=page.getByRole('dialog',{name:'SMS observation'});await dialog.getByText('Captured evidence digests',{exact:true}).waitFor();assert.match(await dialog.innerText(),/current payment eligibility/);await page.setViewportSize({width:390,height:844});assert(await dialog.evaluate(el=>el.getBoundingClientRect().width<=innerWidth));await dialog.getByRole('button',{name:'Close dialog'}).click();
 const before=writes.length;scope=['payments:read'];await page.reload();await page.getByText('Controlled parser 91',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Bind receiving account',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Create parser profile',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Revoke device',exact:true}).count(),0);assert.equal(writes.length,before);assert.equal(errors.length,0);
 console.log(JSON.stringify({boundary:'controlled HTTP, actual Vue',cases:9,pageErrors:errors.length,writes:writes.length}));
}finally{await browser.close();}
