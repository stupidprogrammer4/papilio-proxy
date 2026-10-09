// Real local Vue/API reads. Credentials arrive only through ephemeral stdin.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const credentials=JSON.parse(readFileSync(0,'utf8'));
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
const page=await browser.newPage(),errors=[],failed=[],reads=[],writes=[],responses=[];
let signedIn=false,loggedOut=false;
page.on('pageerror',error=>errors.push(error.message));
page.on('request',req=>{const path=new URL(req.url()).pathname;if(!path.startsWith('/api/'))return;if(req.method()==='GET')reads.push(path);else writes.push({path,method:req.method()});});
page.on('response',res=>{const path=new URL(res.url()).pathname;if(!path.startsWith('/api/'))return;responses.push({path,status:res.status()});if(res.status()>=400&&!(path==='/api/v1/admin/auth/me'&&res.status()===401))failed.push({path,status:res.status()});});
async function fits(){assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Document overflow at mobile width');}
try{
 await page.goto(process.env.PANEL_ORIGIN+'/login');await page.getByLabel('Username',{exact:true}).fill(credentials.username);await page.getByLabel('Password',{exact:true}).fill(credentials.password);credentials.password='';
 const login=page.waitForResponse(res=>new URL(res.url()).pathname==='/api/v1/admin/auth/login');await page.getByRole('button',{name:'Sign in',exact:true}).click();assert.equal((await login).status(),200);signedIn=true;
 await page.goto(process.env.PANEL_ORIGIN+'/settings');const policy=page.getByRole('region',{name:'Payment identifier policy'});await policy.getByText('9999 RIAL',{exact:true}).waitFor();assert.match(await policy.innerText(),/10000/);await policy.getByLabel('Set an explicit payment identifier policy').check();const suffix=policy.getByRole('option',{name:'Four-digit identifier in the RIAL amount',exact:true});assert(await suffix.evaluate(el=>!el.disabled));
 await page.setViewportSize({width:390,height:844});await fits();
 await page.goto(process.env.PANEL_ORIGIN+'/payments');await page.getByRole('heading',{name:'Payments',exact:true}).waitFor();await page.getByText('No parser profiles found.',{exact:true}).waitFor();await page.getByText('No receiving accounts found.',{exact:true}).waitFor();assert(await page.getByRole('button',{name:'Create parser profile',exact:true}).isEnabled());assert(await page.getByRole('button',{name:'Create receiving account',exact:true}).isEnabled());await fits();
 await page.goto(process.env.PANEL_ORIGIN+'/customers');await page.getByText('No customers found.',{exact:true}).waitFor();await fits();
 const logout=page.waitForResponse(res=>new URL(res.url()).pathname==='/api/v1/admin/auth/logout');await page.getByRole('button',{name:'Sign out',exact:true}).click();assert.equal((await logout).status(),204);loggedOut=true;await page.getByRole('button',{name:'Sign in',exact:true}).waitFor();
 assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);assert.deepEqual(writes,[{path:'/api/v1/admin/auth/login',method:'POST'},{path:'/api/v1/admin/auth/logout',method:'POST'}]);
 assert(responses.some(row=>row.path==='/api/v1/admin/payments/sms-origins/parser-profiles'&&row.status===200));assert(responses.some(row=>row.path==='/api/v1/admin/payments/sms-origins/receiving-realms'&&row.status===200));
 console.log(JSON.stringify({boundary:'actual local Vue/API reads, existing owner account; no business mutations',cases:4,mobileWidth:390,pageErrors:errors.length,failedResponses:failed.length,readRequests:reads.length,authWrites:writes.length,logoutStatus:204}));
}finally{
 credentials.password='';
 if(signedIn&&!loggedOut){await page.goto(process.env.PANEL_ORIGIN+'/settings');await page.getByRole('button',{name:'Sign out',exact:true}).click();}
 await browser.close();
}
