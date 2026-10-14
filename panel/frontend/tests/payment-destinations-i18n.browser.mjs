import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';

const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];
const list={data:[],meta:{pager:{total_items:0,total_pages:1,current_page:1,per_page:20,has_prev:false,has_next:false}}};
page.on('pageerror',error=>errors.push(error.message));
page.on('request',request=>{
 if(request.url().includes('/api/'))assert.equal(request.method(),'GET','The localization check must not write records');
});
await page.route(url=>url.pathname.startsWith('/api/'),route=>{
 const path=new URL(route.request().url()).pathname.slice(4);
 const data=path==='/v1/admin/auth/me'
  ? {username:'preview',scopes:['*'],csrf_token:'preview-token'}
  : path==='/v1/admin/branding'
   ? {data:{brand_title:'Papilio'}}
   : path==='/v1/admin/payments/sms-origins/capabilities'
    ? {data:{supported:false,enabled:false,capacity:null,read_available:false,identity_modes:[]}}
    : list;
 return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
});
try{
 await page.goto(process.env.PANEL_ORIGIN+'/payments');
 await page.getByRole('heading',{name:'Payments',exact:true}).waitFor();
 await page.getByTestId('locale-selector').selectOption('fa');
 await page.getByRole('heading',{name:'مقصدهای پرداخت',exact:true}).waitFor();
 await page.getByRole('button',{name:'ساخت مقصد پرداخت',exact:true}).click();
 await page.getByRole('dialog',{name:'ساخت مقصد پرداخت',exact:true}).getByLabel('نام مقصد',{exact:true}).waitFor();
 await page.getByRole('dialog').getByRole('button',{name:'بستن پنجره',exact:true}).click();
 await page.getByRole('heading',{name:'دستگاه‌های پیامکی مورد اعتماد',exact:true}).waitFor();
 await page.getByRole('button',{name:'+ ثبت دستگاه',exact:true}).click();
 await page.getByRole('dialog',{name:'ثبت دستگاه پیامکی',exact:true}).getByLabel('نام دستگاه',{exact:true}).waitFor();
 await page.getByRole('heading',{name:'پارسر و هویت مبدأ',exact:true}).waitFor();
 await page.getByText('مدیریت پارسر پیامک و هویت مبدأ در دسترس نیست؛ بررسی پرداخت‌های موجود همچنان فعال است.',{exact:true}).waitFor();
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert.deepEqual(errors,[]);
 console.log('PASS: payment destination workspace is Persian and fits mobile; GET-only controlled API');
}finally{await browser.close();}
