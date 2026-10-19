// Actual public service page with controlled, read-only HTTP.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],methods=[];
page.on('pageerror',error=>errors.push(error.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);methods.push(request.method());
 assert.equal(request.method(),'GET');
 if(path==='/s/private-token/status')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:{id:72,status:'active',quota_bytes:5*1024**3,used_bytes:1024**3,expires_at:'2026-10-20T08:00:00Z',auto_renew:true,brand_title:'Papilio Service',feed_url:'https://example.invalid/private-feed',qr_enabled:true,support_handle:'papilio_support'}})});
 if(path==='/s/private-token/profiles')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:[{profile_id:5,host_id:null,label:'Primary route',protocol:'vless_tls'}],meta:{pager:{total_pages:1,current_page:1}}})});
 return route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:{message_code:'not_found'}})});
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/service/private-token');
 await page.getByRole('heading',{name:'Papilio Service',exact:true}).waitFor();
 await page.getByText('Available connections',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Copy subscription URL'}).waitFor();
 assert.equal(await page.getByTestId('theme-selector').count(),0);
 await page.emulateMedia({colorScheme:'dark'});
 await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
 await page.emulateMedia({colorScheme:'light'});
 await page.waitForFunction(()=>document.documentElement.dataset.theme==='light');
 await page.getByRole('tab',{name:'Android'}).waitFor();
 await assertClientLink(page,'Hiddify','https://github.com/hiddify/hiddify-app/releases/latest');
 await assertClientLink(page,'v2rayNG','https://github.com/2dust/v2rayNG/releases');
 await page.getByRole('tab',{name:'iOS'}).click();
 await assertClientLink(page,'Hiddify','https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532');
 const streisand=page.getByRole('link',{name:'Get app Streisand'});
 await streisand.waitFor();
 assert.equal(await streisand.getAttribute('href'),'https://apps.apple.com/us/app/streisand/id6450534064');
 await page.getByRole('tab',{name:'Windows'}).click();
 await assertClientLink(page,'Hiddify','https://github.com/hiddify/hiddify-app/releases/latest');
 await assertClientLink(page,'v2rayN','https://github.com/2dust/v2rayN/releases');
 await page.getByRole('tab',{name:'macOS'}).click();
 await assertClientLink(page,'Hiddify','https://github.com/hiddify/hiddify-app/releases/latest');
 await assertClientLink(page,'v2rayN','https://github.com/2dust/v2rayN/releases');
 await page.getByRole('tab',{name:'Linux'}).click();
 await assertClientLink(page,'Hiddify','https://github.com/hiddify/hiddify-app/releases/latest');
 await assertClientLink(page,'v2rayN','https://github.com/2dust/v2rayN/releases');
 await page.locator('.usage-ring').waitFor();
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByText('اتصال‌های در دسترس',{exact:true}).waitFor();
 await page.getByText('حجم').waitFor();
 await page.getByRole('button',{name:'کپی نشانی اشتراک'}).waitFor();
 await page.getByRole('tab',{name:'اندروید'}).waitFor();
 await page.getByRole('tab',{name:'آی‌اواس'}).click();
 await page.getByRole('link',{name:'دریافت برنامه Streisand'}).waitFor();
 assert.deepEqual(errors,[]);assert(methods.length>=2&&methods.every(method=>method==='GET'));
 console.log('Public customer service summary and connection actions render in English and Persian; controlled read-only HTTP.');
}finally{await browser.close();}

async function assertClientLink(page,name,url){
 const link=page.getByRole('link',{name:`Get app ${name}`});
 await link.waitFor();
 assert.equal(await link.getAttribute('href'),url);
 assert.equal(await link.getAttribute('target'),'_blank');
 assert.match(await link.getAttribute('rel'),/noopener/);
}
