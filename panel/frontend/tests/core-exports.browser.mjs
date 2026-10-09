// Vue interaction acceptance with controlled HTTP; native API/core tests are separate.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(), errors=[], writes=[];let failed=true;
const core={id:41,node_id:31,code:'owned',label:'Owned Xray',kind:'xray',supported_protocols:['vless_reality'],application_status:'draft'};
const artifact={filename:'core-41.json',media_type:'application/json',content:'{"inbounds":[{"tag":"owned-91"}]}',sha256:'a'.repeat(64),configurations:[{configuration_id:91,revision:3},{configuration_id:92,revision:7}]};
const respond=(r,data,status=200)=>r.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
page.on('pageerror',e=>errors.push(e.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(), path=new URL(request.url()).pathname.slice(4);
 if(path==='/v1/admin/auth/me')return respond(route,{username:'fixture',scopes:['*'],csrf_token:'fixture-csrf'});
 if(path==='/v1/admin/preferences')return respond(route,{data:{revision:0,values:{brand_title:'Papilio'}}});
 if(path==='/v1/admin/network/nodes/31')return respond(route,{data:{id:31,label:'Owned node',code:'owned'}});
 if(path==='/v1/admin/network/nodes/31/cores')return respond(route,{data:[core],meta:{pager:{total_pages:1}}});
 if(path==='/v1/admin/network/cores/41/export'){
   const data=request.postDataJSON();writes.push(data);assert.equal(request.method(),'POST');
   if(failed){failed=false;return respond(route,{error:{message_code:'core_export_global_conflict'}},409);}
   return respond(route,{data:{core_id:41,node_id:31,kind:'xray',mode:data.mode,application_status:'not_applied',artifacts:[artifact]}});
 }
 return respond(route,{data:[],meta:{pager:{total_pages:1}}});
});
try {
 await page.goto(process.env.PANEL_ORIGIN+'/network/31/cores');
 await page.getByRole('button',{name:'Export core',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Export Owned Xray'});await dialog.waitFor({state:'visible'});
 await dialog.getByLabel('Output mode').selectOption('merged');
 await dialog.getByRole('button',{name:'Generate export',exact:true}).click();
 await dialog.getByRole('alert').waitFor();assert.match(await dialog.getByRole('alert').innerText(),/DNS/);
 assert.equal(await dialog.getByLabel('Output mode').inputValue(),'merged');
 await dialog.getByLabel('Output mode').selectOption('isolated');
 await dialog.getByRole('button',{name:'Generate export',exact:true}).click();
 await dialog.getByRole('heading',{name:'core-41.json'}).waitFor();
 assert.match(await dialog.innerText(),/#91 · revision 3, #92 · revision 7/);
 await dialog.getByText('Preview server configuration',{exact:true}).click();
 assert.equal(await dialog.locator('textarea').inputValue(),artifact.content);
 const download=page.waitForEvent('download');await dialog.getByRole('button',{name:'Download file'}).click();assert.equal((await download).suggestedFilename(),'core-41.json');
 await page.setViewportSize({width:390,height:844});
 assert(await dialog.evaluate(el=>{const rect=el.getBoundingClientRect();return rect.left>=0&&rect.right<=innerWidth;}));
 await dialog.getByRole('button',{name:'Close dialog'}).click();await dialog.waitFor({state:'hidden'});
 await page.getByRole('button',{name:'Export core',exact:true}).click();
 assert.equal(await dialog.locator('textarea').count(),0);
 assert.equal(await dialog.getByLabel('Output mode').inputValue(),'isolated');
 assert.deepEqual(writes,[{mode:'merged'},{mode:'isolated'}]);assert.deepEqual(errors,[]);
 console.log('Core identity, conflict recovery, revision preview, download, secret clearing and mobile modal passed; controlled HTTP.');
} finally {await browser.close();}
