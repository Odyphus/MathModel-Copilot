/* Real local HTTP/Chrome acceptance plus explicitly synthetic display scenarios.
 * node tools/verify_dashboard_continuity.js URL NEW_OUTPUT_DIR
 * Optional MATHMODEL_PLAYWRIGHT_MODULE points to an installed Playwright module.
 * No business writes, AI requests or remote sync. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.MATHMODEL_PLAYWRIGHT_MODULE||'playwright');
const [url,directory]=process.argv.slice(2),out=path.resolve(directory),origin=new URL(url).origin;
assert(['127.0.0.1','localhost'].includes(new URL(url).hostname));fs.mkdirSync(out,{recursive:false});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'}),context=await browser.newContext({viewport:{width:1440,height:1000},locale:'zh-CN'}),page=await context.newPage();
 const checks=[],errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push({url:r.url(),method:r.method()}));
 const pass=name=>checks.push(name),clone=value=>JSON.parse(JSON.stringify(value));
 try{
  const read=async()=>{const response=await context.request.get(origin+'/api/snapshot',{headers:{'X-Copilot-Read':'1'}});assert.equal(response.status(),200);return(await response.json()).result;};
  const before=await read();await page.goto(origin);await page.getByRole('heading',{name:'项目总览',exact:true}).waitFor();
  assert.equal(await page.locator('#navigation button').count(),4);
  const asset=await context.request.get(origin+'/workbench.js');assert.equal(asset.status(),200);assert((await asset.text()).includes('changeItems'));
  for(const label of ['各问进展','成果与依据','论文准备','项目总览'])await page.getByRole('button',{name:label,exact:true}).click();
  pass('real HTTP serves the reusable module and all four existing destinations');

  // Only these browser responses are synthetic; the real project is unchanged.
  let sample={...clone(before),project_id:'continuity-browser-fixture',revision:1,state_hash:'a'.repeat(64),file_observation_hash:'b'.repeat(64),identity:{...clone(before.identity),demo:true,title:'工作台交互验收（合成演示）'},objects:{},tasks:{},requirements:{},changes:[],decisions:[],members:{},status:{requirements:{rows:[],questions:{Q1:'pending'}},blockers:[],next_action:'比较初始条件的两种解释',submission:{ready:false,state:'unknown',blockers:[]}}};
  const param={id:'params.Q1@1',key:'params.Q1',kind:'ParameterSet',status:'frozen',effective_status:'frozen',is_current:true,current_errors:[],payload:{question:'Q1',entries:Array.from({length:24},(_,i)=>({meaning:'容量参数 '+(i+1),current_value:12000+i,unit:'kWh'}))},dependencies:[],files:[]};
  const ambiguity={object_id:'interpretation.Q1@1',kind:'AmbiguityEntry',question:'Q1',status:'open',freeze_gate:'blocked',current_errors:[],mathematical_validation:'not_claimed',payload:{question:'Q1',ambiguity_id:'AMB-Q1-1',source_anchor:'题面第一问的初始条件',status:'open',severity:'high',interpretations:['固定初始储能为 6,000 千瓦时','只要求首尾储能相等，初始值参与优化'],impact:'初始条件不同，线性规划（LP）的可行域与成本比较可能不同。'}};
  sample.objects[param.id]=param;sample.objects[ambiguity.object_id]={id:ambiguity.object_id,key:'interpretation.Q1',kind:ambiguity.kind,status:'frozen',effective_status:'frozen',is_current:true,current_errors:[],payload:ambiguity.payload};sample.status.interpretations=[ambiguity];
  let hold=false,release=null;const refreshed=async()=>{await page.waitForFunction(()=>!document.getElementById('refresh').disabled);};
  await page.route('**/api/snapshot',async route=>{if(hold)await new Promise(resolve=>{release=resolve;});const response=clone(sample);response.checked_at=new Date().toISOString();await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,result:response})});});
  await page.goto(origin);await page.getByRole('heading',{name:'需要你判断',exact:true}).waitFor();
  assert(await page.getByText('固定初始储能为 6,000 千瓦时',{exact:true}).isVisible());assert.match(await page.locator('main').innerText(),/线性规划（LP）/);assert.equal(await page.getByText('已获人工批准',{exact:true}).count(),0);
  await page.getByText('与 AI 继续讨论',{exact:true}).click();assert.match(await page.getByLabel('可复制的讨论提纲').inputValue(),/没有在页面作出选择/);
  await page.getByRole('button',{name:'复制讨论提纲',exact:true}).click();await page.waitForFunction(()=>/已复制|手动复制/.test(document.getElementById('toast').textContent));pass('structured alternatives impact and usable discussion copy; no invented adoption');
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});const dimensions=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(dimensions.scroll<=width+1);await page.screenshot({path:path.join(out,'decisions-'+width+'.png'),fullPage:true});}
  pass('desktop and mobile decision panels have no horizontal overflow');await page.setViewportSize({width:1440,height:1000});

  await page.getByRole('button',{name:'各问进展',exact:true}).click();await page.getByText('方案、假设与数据',{exact:true}).click();await page.locator('button[data-object-id="params.Q1@1"]').click();
  const detail=page.getByRole('dialog');await page.locator('#detail').evaluate(node=>{node.scrollTop=400;});const oldScroll=await detail.evaluate(node=>node.scrollTop);
  const oldElement=await page.locator('#detail-heading').elementHandle();hold=true;await page.evaluate(()=>{dispatchEvent(new Event('blur'));dispatchEvent(new Event('focus'));});await page.getByText('正在重新核对。下方暂保留上次读取的内容，请等待更新后再判断。',{exact:true}).last().waitFor();
  assert(await detail.isVisible());hold=false;release();await refreshed();assert(await oldElement.evaluate(node=>node.isConnected));assert(Math.abs(await detail.evaluate(node=>node.scrollTop)-oldScroll)<3);pass('unchanged refresh preserves dialog DOM and reading position');

  sample.objects[param.id].payload.entries[0].current_value=18000;sample.objects[param.id].effective_status='stale';sample.objects[param.id].current_errors=['相关文件变化'];sample.file_observation_hash='c'.repeat(64);
  await page.evaluate(()=>{dispatchEvent(new Event('blur'));dispatchEvent(new Event('focus'));});await refreshed();assert(await detail.isVisible());assert.match(await detail.innerText(),/18000/);assert.doesNotMatch(await detail.innerText(),/12000\s/);assert.match(await detail.innerText(),/需要重新检查/);assert(Math.abs(await detail.evaluate(node=>node.scrollTop)-oldScroll)<60);pass('same-revision drift refreshes open values and stale state without closing the reader');
  await page.keyboard.press('Escape');await page.getByRole('button',{name:'项目总览',exact:true}).click();await page.getByRole('heading',{name:'自上次已读后的变化',exact:true}).waitFor();assert.match(await page.locator('.return-summary').innerText(),/需要重检/);
  await page.reload();await page.getByRole('heading',{name:'自上次已读后的变化',exact:true}).waitFor();
  await page.getByRole('button',{name:'这批变化已看过',exact:true}).click();assert.equal(await page.getByRole('heading',{name:'自上次已读后的变化',exact:true}).count(),0);assert(await page.getByRole('heading',{name:'需要你判断',exact:true}).isVisible());pass('unread changes survive reload; explicit read marker does not clear decisions or stale facts');

  hold=true;await page.getByRole('button',{name:'刷新进展',exact:true}).click();await page.getByRole('button',{name:'各问进展',exact:true}).click();hold=false;release();await refreshed();assert(await page.getByRole('heading',{name:'各问进展',exact:true}).isVisible());pass('navigation requested during identical refresh is not lost');
  await page.getByRole('button',{name:'成果与依据',exact:true}).click();await page.getByLabel('查看内容',{exact:true}).selectOption('all');await page.getByLabel('搜索成果',{exact:true}).fill('参数');
  sample.state_hash='d'.repeat(64);sample.revision=2;await page.evaluate(()=>{dispatchEvent(new Event('blur'));dispatchEvent(new Event('focus'));});await refreshed();assert.equal(await page.getByLabel('搜索成果',{exact:true}).inputValue(),'参数');assert.equal(await page.getByLabel('查看内容',{exact:true}).inputValue(),'all');pass('changed observation keeps result filter and search selection');

  await page.locator('button[data-object-id="params.Q1@1"]').click();await page.unroute('**/api/snapshot');await page.route('**/api/snapshot',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({ok:false,message:'合成网络故障'})}));await page.evaluate(()=>{dispatchEvent(new Event('blur'));dispatchEvent(new Event('focus'));});await page.getByRole('heading',{name:'项目暂时不可用',exact:true}).waitFor();assert(!await detail.isVisible());assert.equal(await page.locator('#detail-body').innerText(),'');assert(await page.locator('#diagnostic').isDisabled());pass('failed refresh clears old facts and disables use of obsolete detail');
  const after=await read();assert.equal(before.authority_file_sha256,after.authority_file_sha256);assert.equal(before.file_observation_hash,after.file_observation_hash);assert.equal(before.revision,after.revision);assert.equal(requests.filter(x=>x.method!=='GET').length,0);assert.deepEqual(errors,[]);pass('no POST, AI invocation, authority mutation or bound-file mutation');
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,checks,errors,browser:browser.version(),scope:'Real local HTTP navigation plus explicitly synthetic UI responses. No claim of modeling correctness or end-user usability benchmark.',authority_unchanged:true,requests:requests.length},null,2));console.log(JSON.stringify({passed:true,checks:checks.length,output:out}));
 }finally{await browser.close();}
})().catch(e=>{fs.writeFileSync(path.join(out,'failure.txt'),e.stack);console.error(e);process.exitCode=1;});
