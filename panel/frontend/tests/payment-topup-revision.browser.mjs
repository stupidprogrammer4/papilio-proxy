import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';

const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],writes=[];
page.setDefaultTimeout(8000);
page.on('pageerror',error=>errors.push(error.message));
const rows=[
 {id:700,revision:4,customer_id:42,amount_rial:100000,requested_amount_rial:100000,status:'pending',bank_reference:null,payment_identifier_mode:'exact_requested',payment_identifier_code4:null,created_at:'2026-10-08T00:00:00Z'},
 {id:701,revision:9,customer_id:43,amount_rial:200000,requested_amount_rial:200000,status:'pending',bank_reference:null,payment_identifier_mode:'exact_requested',payment_identifier_code4:null,created_at:'2026-10-08T00:00:00Z'},
];
const paged=data=>({data,meta:{pager:{total_items:data.length,total_pages:1,current_page:1,per_page:20,has_prev:false,has_next:false}}});
await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
 const req=route.request(),path=new URL(req.url()).pathname.slice(4),method=req.method();
 let body=paged([]);
 if(path==='/v1/admin/auth/me')body={username:'topup-revision-browser',scopes:['*'],csrf_token:'controlled'};
 else if(path==='/v1/admin/preferences')body={data:{revision:0,values:{brand_title:'Papilio'}}};
 else if(path==='/v1/admin/payments/topups'&&method==='GET')body=paged(rows);
 else if(path==='/v1/admin/payments/sms'&&method==='GET')body=paged([]);
 else if(/^\/v1\/admin\/payments\/topups\/(700|701)\/(approve|reject)$/.test(path)&&method==='POST'){
  const [,id,action]=path.match(/^\/v1\/admin\/payments\/topups\/(700|701)\/(approve|reject)$/);
  const input=req.postDataJSON(),row=rows.find(candidate=>candidate.id===Number(id));
  writes.push({id:Number(id),action,input});
  assert.equal(input.expected_revision,row.revision);
  row.status=action==='approve'?'approved':'rejected';row.revision++;
  body={data:row};
 }
 return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
});
try{
 await page.goto(`${process.env.PANEL_ORIGIN}/payments`);
 await page.getByRole('heading',{name:'Payments',exact:true}).waitFor();
 await page.getByRole('row').filter({hasText:'700'}).click();
 await page.getByLabel('Bank transaction reference').fill('BANK-700-REF');
 await page.getByRole('button',{name:'Approve and credit wallet',exact:true}).click();
 await page.getByRole('row').filter({hasText:'701'}).click();
 await page.getByRole('button',{name:'Reject request',exact:true}).click();
 assert.deepEqual(writes,[
  {id:700,action:'approve',input:{expected_revision:4,bank_reference:'BANK-700-REF'}},
  {id:701,action:'reject',input:{expected_revision:9}},
 ]);
 assert.deepEqual(errors,[]);
 console.log('PASS: actual Payments Vue flow sends selected topup revision with approve and reject');
}finally{await browser.close();}
