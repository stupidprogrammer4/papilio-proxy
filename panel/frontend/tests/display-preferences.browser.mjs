// Actual Vue UI; authentication HTTP is controlled, no database is exercised.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {mkdir} from 'node:fs/promises';

const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const context=await browser.newContext({viewport:{width:390,height:844}});
const page=await context.newPage(),errors=[];
let workspaceContext;
page.setDefaultTimeout(5000);
page.on('pageerror',error=>errors.push(error.message));
await page.route(url=>url.pathname.startsWith('/api/'),route=>route.fulfill({
 status:401,contentType:'application/json',
 body:JSON.stringify({success:false,error:{message_code:'admin_unauthorized',message:'DO NOT DISPLAY SERVER TEXT'}}),
}));
try{
 await page.goto(process.env.PANEL_ORIGIN+'/login');
 await page.getByTestId('theme-selector').selectOption('light');
 assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
 assert.equal(await page.locator('html').evaluate(el=>getComputedStyle(el).colorScheme),'light');
 await page.getByTestId('locale-selector').selectOption('fa');
 assert.equal(await page.locator('html').getAttribute('lang'),'fa');
 assert.equal(await page.locator('html').getAttribute('dir'),'rtl');
 workspaceContext=await browser.newContext({viewport:{width:390,height:844}});
 const workspace=await workspaceContext.newPage();
 workspace.setDefaultTimeout(5000);
 workspace.on('pageerror',error=>errors.push(error.message));
 await workspace.route(url=>url.pathname.startsWith('/api/'),route=>{
  const request=route.request(),path=new URL(request.url()).pathname.slice(4);
  assert.equal(request.method(),'GET');
  const body=path==='/v1/admin/auth/me'
   ? {username:'browser-fixture',scopes:['*'],csrf_token:'controlled-browser-token'}
   : path==='/v1/admin/branding'
    ? {data:{brand_title:'Browser fixture'}}
    : path==='/v1/admin/customers/creation-policy'
     ? {data:{is_active:true,services_enabled:true,renewals_enabled:true}}
     : {data:[],meta:{pager:{total_items:0,total_pages:1,current_page:1,per_page:20,has_prev:false,has_next:false}}};
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 });
 await workspace.goto(process.env.PANEL_ORIGIN+'/customers');
 await workspace.getByTestId('locale-selector').selectOption('fa');
 await workspace.getByRole('button',{name:'بازکردن منو',exact:true}).click();
 await workspace.getByRole('link',{name:'مشتری‌ها',exact:true}).waitFor();
 await workspace.getByRole('link',{name:'پلن‌ها و باندل‌ها',exact:true}).waitFor();
 await workspace.waitForFunction(()=>{
  const bounds=document.querySelector('.sidebar')?.getBoundingClientRect();
  return bounds&&bounds.x>=0&&bounds.right<=innerWidth;
 });
 const drawer=await workspace.locator('.sidebar').boundingBox();
 assert(drawer&&drawer.x>=0&&drawer.x+drawer.width<=390);
 await workspace.locator('.sidebar').getByRole('button',{name:'بستن منو',exact:true}).click();
 await workspace.reload();
 await workspace.getByRole('button',{name:'بازکردن منو',exact:true}).waitFor();
 assert.equal(await workspace.locator('html').getAttribute('dir'),'rtl');
 assert(await workspace.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert.equal(await page.locator('.login-card').evaluate(el=>getComputedStyle(el).textAlign),'right');
 await page.getByRole('heading',{name:'خوش آمدید',exact:true}).waitFor();
 await page.getByLabel('نام کاربری',{exact:true}).fill('test-user');
 await page.getByLabel('رمز عبور',{exact:true}).fill('test-password');
 await page.getByRole('button',{name:'ورود',exact:true}).click();
 await page.getByRole('alert').getByText('نشست شما پایان یافته است. دوباره وارد شوید.',{exact:true}).waitFor();
 assert(!await page.locator('body').innerText().then(text=>text.includes('DO NOT DISPLAY SERVER TEXT')));
 await page.getByTestId('locale-selector').selectOption('en');
 await page.getByRole('alert').getByText('Your session ended. Sign in again.',{exact:true}).waitFor();
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.reload();
 assert.equal(await page.locator('html').getAttribute('dir'),'rtl');
 assert.equal(await page.getByTestId('theme-selector').inputValue(),'light');
 await mkdir('.local-review/ui-screenshots',{recursive:true});
 await page.screenshot({path:'.local-review/ui-screenshots/fa-light-login.png',animations:'disabled'});
 await page.emulateMedia({colorScheme:'dark'});
 await page.getByTestId('theme-selector').selectOption('system');
 await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
 await page.emulateMedia({colorScheme:'light'});
 await page.waitForFunction(()=>document.documentElement.dataset.theme==='light');
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.evaluate(()=>{
  localStorage.setItem('papilio.locale','unsupported');
  localStorage.setItem('papilio.theme','unsupported');
 });
 await page.reload();
 await page.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();
 assert.equal(await page.getByTestId('theme-selector').inputValue(),'dark');
 assert.equal(await page.locator('html').getAttribute('dir'),'ltr');
 await page.screenshot({path:'.local-review/ui-screenshots/en-dark-login.png',animations:'disabled'});
 await page.addInitScript(()=>{
  Object.defineProperty(window,'localStorage',{value:{
   getItem(){throw new Error('Storage unavailable');},
   setItem(){throw new Error('Storage unavailable');},
  }});
 });
 await page.reload();
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('status').getByText('تغییرات در این مرورگر ذخیره نمی‌شوند.',{exact:true}).waitFor();
 assert.equal(await page.locator('html').getAttribute('dir'),'rtl');
 assert.deepEqual(errors,[]);
 console.log('PASS: language, direction, translated error, persistence, system theme, invalid settings and mobile fit');
}finally{
 if(workspaceContext)await workspaceContext.close();
 await context.close();
 await browser.close();
}
