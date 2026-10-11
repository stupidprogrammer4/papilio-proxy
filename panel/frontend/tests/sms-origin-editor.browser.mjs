// Vue acceptance with controlled HTTP only; parser/financial acceptance is native separately.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const errors=[],writes=[],diagnostics=[];
const capacity={enabled:true,page_size:5,max_page_size:20,max_profiles:50,max_profile_bytes:200000,max_rules_per_field:20,max_marker_chars:200,max_clauses:50,max_message_bytes:4000,max_realms:50,max_aliases_per_realm:20,max_match_candidates:20,original_timestamp_future_seconds:60,original_timestamp_max_age_seconds:86400};
const capabilities={supported:true,configured:true,read_available:true,enabled:true,capacity,parser_modes:['legacy_strict_reference','labelled_credit'],identity_modes:['bank_reference_required','trusted_origin_fingerprint'],amount_relations:['label_before_amount','amount_before_label'],units:['rial','toman'],required_origin_fields:['kind','original_provider_timestamp_ms','original_sender','canonicalization_revision'],canonicalization_revision:1,source_assurance:'enrolled_sender_declared_metadata',bank_settlement_verified:false};
const valid={mode:'labelled_credit',credit_markers:['Synthetic credit'],debit_markers:['Synthetic debit'],clause_separators:['\n'],deposit_relations:[{marker:'Synthetic deposit',relation:'label_before_amount',implicit_unit:null}],balance_relations:[],reference_labels:[],rial_labels:['rial'],toman_labels:['toman'],grouping_separators:[','],case_sensitive:false};
async function malformed(value){
 const page=await browser.newPage();page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')diagnostics.push(message.text());});
 await page.route(url=>url.pathname.startsWith('/api/'),route=>{
  const req=route.request(),path=new URL(req.url()).pathname.slice(4);
  const respond=data=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  if(req.method()!=='GET')writes.push({path,body:req.postDataJSON()});
  if(path==='/v1/admin/auth/me')return respond({username:'controlled-sms-editor',scopes:['*'],csrf_token:'controlled-csrf'});
  if(path==='/v1/admin/preferences')return respond({data:{revision:0,values:{brand_title:'Papilio'}}});
  if(path==='/v1/admin/payments/sms-origins/capabilities')return respond({data:capabilities});
  if(path==='/v1/admin/payments/sms-origins/parser-profiles'&&req.method()==='POST')return respond({data:{id:41,title:req.postDataJSON().title,is_active:false,revision:1,current_parser_revision_id:91,created_at:'2026-10-08T00:00:00Z'}});
  return respond({data:[],meta:{pager:{total_pages:1,total_items:0}}});
 });
 await page.goto(process.env.PANEL_ORIGIN+'/payments');
 await page.getByRole('button',{name:'Create parser profile',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Create parser profile',exact:true});
 await dialog.getByLabel('Profile title').fill('Controlled malformed draft');
 await dialog.getByText('Advanced definition JSON',{exact:true}).click();
 const editor=dialog.getByLabel('Literal parser definition JSON');const draft=JSON.stringify(value,null,2);
 await editor.fill(draft);
 try{await dialog.getByText('The definition JSON cannot be displayed as literal rules. Correct its arrays in the advanced editor.',{exact:true}).waitFor({timeout:3000});}catch(error){console.error(JSON.stringify({dialog:await dialog.innerText(),diagnostics}));throw error;}
 assert.equal(await editor.inputValue(),draft,'malformed draft was discarded');
 assert.equal(errors.length,0,'malformed JSON crashed Vue rendering');
 await dialog.getByRole('button',{name:'Create profile',exact:true}).click();
 await dialog.getByRole('alert').first().waitFor();
 assert.equal(await editor.inputValue(),draft,'failed validation discarded the draft');
 assert.equal(writes.length,0,'malformed JSON reached API');
 if(value.credit_markers[0]&&typeof value.credit_markers[0]==='object'){
  await editor.fill(JSON.stringify(valid,null,2));
  await dialog.getByText('Clause separators',{exact:true}).waitFor();
  await dialog.getByLabel('Required amount suffix (optional)').fill('+');
  await dialog.getByRole('button',{name:'Create profile',exact:true}).click();
  await dialog.waitFor({state:'hidden'});
  assert.equal(writes.length,1);assert.deepEqual(writes[0].body.definition.clause_separators,['\n']);assert.equal(writes[0].body.definition.deposit_relations[0].required_amount_suffix,'+');
 }
 await page.close();
}
try{
 await malformed({...valid,deposit_relations:[null]});
 await malformed({...valid,deposit_relations:[{...valid.deposit_relations[0],required_amount_suffix:{}}]});
 await malformed({...valid,credit_markers:[{}]});
 console.log(JSON.stringify({boundary:'controlled HTTP, actual Vue',cases:4,pageErrors:errors.length,writes:writes.length}));
} catch(error){console.error(JSON.stringify({pageErrors:errors,writes:writes.length}));throw error;} finally {await browser.close();}
