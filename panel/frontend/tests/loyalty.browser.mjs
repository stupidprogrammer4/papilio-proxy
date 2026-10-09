import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],writes=[];let attempts=0;
const tier={id:1,code:'bronze',title:'Bronze',minimum_bytes:107374182400,discount_bps:1000,is_enabled:true,revision:1};
const values={enabled:true,tier_basis:'net_purchases',unlimited_credit_mode:'equivalent',unlimited_equivalent_bytes:107374182400,unlimited_plan_bytes:{},first_purchase_basis:"net_purchases",first_purchase_discount_bps:500,combination_mode:'best',maximum_discount_bps:10000,minimum_qualifying_rial:1,renewal_tier_discount:true,notify_tier_changes:true,notify_discounts:true};
const respond=(r,data,status=200)=>r.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
page.on('pageerror',e=>errors.push(e.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4),method=request.method();
 if(path==='/v1/admin/auth/me')return respond(route,{username:'fixture',scopes:['*'],csrf_token:'fixture-csrf'});
 if(path==='/v1/admin/preferences')return respond(route,{data:{revision:0,values:{brand_title:'Papilio'}}});
 if(path==='/v1/admin/loyalty/tiers'&&method==='GET')return respond(route,{data:[tier],meta:{pager:{total_items:1,total_pages:1}}});
 if(path==='/v1/admin/loyalty/policy'&&method==='GET')return respond(route,{data:{revision:2,values}});
 if(path==='/v1/admin/loyalty/policy'&&method==='PUT'){const body=request.postDataJSON();writes.push(body);if(++attempts===1)return respond(route,{error:{message_code:'request_failed'}},503);return respond(route,{data:{revision:3,values:body.values}});}
 if(path==='/v1/admin/loyalty/tiers/1'&&method==='PUT'){const body=request.postDataJSON();writes.push(body);return respond(route,{data:{...tier,...body,revision:2}});}
 return respond(route,{data:[],meta:{pager:{total_items:0,total_pages:1}}});
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/loyalty');
 await page.getByRole('button',{name:'Edit policy',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Loyalty and discount rules'});await dialog.waitFor({state:'visible',timeout:5000});
 await dialog.getByLabel('First-purchase eligibility').selectOption('lifetime_purchases');await dialog.getByLabel('Discount combination').selectOption('sequential');await dialog.getByLabel('First-purchase discount (basis points)').fill('750');
 await dialog.getByRole('button',{name:'Save policy',exact:true}).click();await dialog.getByRole('alert').waitFor();
 assert.equal(await dialog.getByLabel('First-purchase discount (basis points)').inputValue(),'750');
 await dialog.getByRole('button',{name:'Save policy',exact:true}).click();await dialog.waitFor({state:'hidden'});
 assert.equal(writes[0].expected_revision,2);assert.equal(writes[1].expected_revision,2);assert.equal(writes[1].values.combination_mode,'sequential');assert.equal(writes[1].values.first_purchase_basis,'lifetime_purchases');
 await page.getByRole('button',{name:'Edit Bronze',exact:true}).click();
 const tierDialog=page.getByRole('dialog',{name:'Edit Bronze'});await tierDialog.getByLabel('Discount (basis points; 100 = 1%)').fill('1250');await tierDialog.getByRole('button',{name:'Save tier'}).click();await tierDialog.waitFor({state:'hidden'});
 assert.equal(writes[2].expected_revision,1);assert.equal(writes[2].discount_bps,1250);
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Edit policy',exact:true}).click();await dialog.waitFor({state:'visible'});
 assert(await dialog.evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}));assert.deepEqual(errors,[]);
 console.log('Policy modes, retained retry, tier identity and mobile dialog passed; controlled HTTP.');
}finally{await browser.close();}
