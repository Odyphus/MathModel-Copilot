/* Optional browser acceptance against an already running local Core project.
 * node tools/verify_dashboard_ui.js --url http://127.0.0.1:PORT --output NEW_DIR --channel chrome
 * Real data navigation is followed by explicitly synthetic negative display cases.
 * Never writes business state. Node and Playwright are optional verification tools. */
'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto'),assert=require('assert/strict');
const {chromium}=require(process.env.MATHMODEL_PLAYWRIGHT_MODULE||'playwright');
const args={};for(let i=2;i<process.argv.length;i+=2){assert(['--url','--output','--channel'].includes(process.argv[i]));assert(process.argv[i+1]);args[process.argv[i].slice(2)]=process.argv[i+1];}
assert(args.url&&args.output);const url=new URL(args.url);assert(url.protocol==='http:'&&['127.0.0.1','localhost'].includes(url.hostname));
const out=path.resolve(args.output);fs.mkdirSync(out,{recursive:false});
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
(async()=>{
 const browser=await chromium.launch({headless:true,...(args.channel?{channel:args.channel}:{})});
 const context=await browser.newContext({viewport:{width:1440,height:1024},locale:'zh-CN'}),page=await context.newPage(),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 const pass=name=>checks.push({name,status:'pass'});
 try {
  const read=async()=>{const r=await context.request.get(url.origin+'/api/snapshot',{headers:{'X-Copilot-Read':'1'}});assert.equal(r.status(),200);return(await r.json()).result;};
  const before=await read(),assets={};assert.equal(before.read_only,true);assert.equal(before.identity.demo,false);
  for(const name of ['index.html','app.js','styles.css','data.js']){const r=await context.request.get(url.origin+(name==='index.html'?'/':'/'+name));assert.equal(r.status(),200);assets[name]=hash(await r.body());}
  fs.writeFileSync(path.join(out,'before.json'),JSON.stringify(before,null,2));
  const clean=async()=>{const text=await page.locator('body').innerText();assert(!text.includes(before.project_id));assert(!text.includes(before.state_hash));assert.doesNotMatch(text,/\b(?:RUN|CHECK|REQ|CLAIM|PAPER)-[A-Za-z0-9_.-]+(?:@\d+)?|\b[0-9a-f]{16,}\b|Historical\/research|Formal visual review|awaiting_submission| -> (?:running|completed)|projection\./);return text;};
  await page.goto(url.origin+'/');await page.getByRole('heading',{name:'项目总览',exact:true}).waitFor();
  assert.equal(await page.locator('#navigation button').count(),4);assert((await clean()).includes('本机项目记录'));pass('four destinations and explicit local scope');
  const dimensions=[];
  for(const width of [1440,760,390]){await page.setViewportSize({width,height:1024});const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(size.scroll<=size.width+1);dimensions.push(size);await page.screenshot({path:path.join(out,'overview-'+width+'.png'),fullPage:true});}
  for(const button of await page.locator('#navigation button').all()){const box=await button.boundingBox();assert(box&&box.x>=0&&box.x+box.width<=391,'Every mobile navigation label must be in view');}
  pass('desktop narrow and mobile overview without horizontal overflow');await page.setViewportSize({width:1440,height:1024});
  await page.getByRole('button',{name:'各问进展',exact:true}).click();
  for(const summary of await page.getByText('逐项查看题目要求',{exact:true}).all())await summary.click();
  const requirements=Object.entries(before.requirements).filter(([,r])=>r.active===true),mappings=[];assert(requirements.length>0);
  for(const [id,r] of requirements){const button=page.locator('button[data-object-id='+JSON.stringify(id)+']');assert.equal(await button.count(),1);assert(await button.isVisible());if(/[\u3400-\u9fff]/u.test(r.definition.requested_action))assert((await button.innerText()).includes(r.definition.requested_action));mappings.push({id,action:r.definition.requested_action});}
  if(before.requirements['REQ-Q2-001']?.definition?.source_anchor==='Problem B Task two, Table 1 parameter group 1; situation single'){
   const button=page.locator('button[data-object-id="REQ-Q2-001"]');assert((await button.innerText()).includes('第1组参数 · 单工序'));await button.click();assert(await page.getByRole('dialog').getByText('第1组单工序调度结果',{exact:true}).isVisible());await page.keyboard.press('Escape');
  }
  await clean();await page.screenshot({path:path.join(out,'questions.png'),fullPage:true});pass('all active requirements readable including identical descriptions');
  const dependent=Object.values(before.tasks).find(t=>t.depends_on?.length&&t.outputs?.length);
  if(dependent){
   for(const summary of await page.getByText('任务安排与产出',{exact:true}).all())await summary.click();
   await page.locator('button[data-object-id='+JSON.stringify(dependent.id)+']').click();const dialog=page.getByRole('dialog');
   await dialog.getByText('先完成的任务',{exact:true}).click();await dialog.getByText('这项任务的产出',{exact:true}).click();
   for(const id of dependent.outputs)assert(await dialog.locator('button[data-object-id='+JSON.stringify(id)+']').isVisible());
   await clean();await page.screenshot({path:path.join(out,'task-detail.png')});
   await dialog.locator('button[data-object-id='+JSON.stringify(dependent.depends_on[0])+']').click();await page.locator('#detail-back').click();assert(await dialog.getByText('这项任务的产出',{exact:true}).isVisible());await page.keyboard.press('Escape');pass('task prerequisites output traversal and back navigation');
  }else checks.push({name:'task prerequisites navigation',status:'not_applicable',reason:'No task with prerequisites and outputs in this project'});
  await page.getByRole('button',{name:'成果与依据',exact:true}).click();await clean();await page.screenshot({path:path.join(out,'results.png'),fullPage:true});
  for(const category of ['process','basis','all']){await page.getByLabel('查看内容',{exact:true}).selectOption(category);await clean();}
  const currentRuns=Object.values(before.objects).filter(o=>o.kind==='RunRecord'&&o.is_current!==false);await page.getByLabel('查看内容',{exact:true}).selectOption('process');for(const o of currentRuns){const label=await page.locator('button[data-object-id='+JSON.stringify(o.id)+']').innerText();assert.match(label,/计算记录/);assert(!label.includes(o.id));}
  await page.getByLabel('搜索成果',{exact:true}).fill('不存在的筛选内容');assert(await page.getByRole('heading',{name:'没有对应记录'}).isVisible());await page.getByLabel('搜索成果',{exact:true}).fill('');pass('result categories filtering and readable run labels');
  const result=Object.values(before.objects).find(o=>o.kind==='ResultRecord'&&o.is_current!==false&&o.files?.some(f=>/\.(json|md|csv|txt)$/i.test(f.path)&&f.byte_size<262144));
  if(result){await page.getByLabel('查看内容',{exact:true}).selectOption('results');await page.locator('button[data-object-id='+JSON.stringify(result.id)+']').click();await page.getByRole('dialog').getByText('查看相关文件',{exact:true}).click();const b=page.getByRole('dialog').locator('button[data-file-path]').first();await b.click();await page.locator('.file-content').waitFor();assert((await page.locator('.file-content').innerText()).length>0);await page.keyboard.press('Escape');pass('version bound source text remains accessible');}
  await page.getByRole('button',{name:'论文准备',exact:true}).click();await clean();if(!before.status.submission.ready)assert(await page.getByText('正式提交条件尚未满足',{exact:true}).isVisible());await page.screenshot({path:path.join(out,'paper.png'),fullPage:true});pass('submission blockers remain visible in Chinese');
  await page.getByRole('button',{name:'查看本机变化',exact:true}).click();await clean();assert((await page.locator('main').innerText()).includes('不表示队友的最新进展'));pass('history does not imply remote team synchronization');
  const after=await read();assert.equal(after.authority_file_sha256,before.authority_file_sha256);assert.equal(after.revision,before.revision);assert.equal(after.file_observation_hash,before.file_observation_hash);pass('real project and observed files unchanged');

  // These cases explicitly simulate responses; they are never claimed as Core observations.
  const show=async v=>{await page.unroute('**/api/snapshot');await page.route('**/api/snapshot',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,result:v})}));await page.goto(url.origin+'/');await page.getByRole('heading',{name:'项目总览',exact:true}).waitFor();};
  const blank=structuredClone(before);blank.identity.demo=true;blank.objects={};blank.tasks={};blank.requirements={};blank.members={};blank.changes=[];blank.status={requirements:{rows:[],questions:{},total:0,verified:0},current_task:null,blockers:[],next_action:'先列出题目要求',submission:{ready:false,state:'unknown',blockers:[],audit_id:null,package_id:null}};
  await show(blank);for(const title of ['主要成果','待解决问题','需要你确认','论文准备'])assert.equal(await page.getByRole('heading',{name:title,exact:true}).count(),0);assert(await page.getByRole('heading',{name:'从题目要求开始'}).isVisible());pass('synthetic empty state hides optional panels');
  const hostile=structuredClone(blank);hostile.identity.title='<img src=x onerror=alert(1)> 测试项目';hostile.status.blockers=['Unsupported manual approval mechanism: inspect actual source'];await show(hostile);assert.equal(await page.locator('img').count(),0);assert((await page.locator('body').innerText()).includes('<img'));assert(!(await page.locator('main').innerText()).includes('Unsupported manual'));await page.getByText('查看具体原因（原文）',{exact:true}).click();assert((await page.locator('main').innerText()).includes('Unsupported manual approval'));pass('synthetic untrusted title is literal and unknown error keeps original reason');
  await page.unroute('**/api/snapshot');await page.goto(url.origin+'/');await page.getByRole('heading',{name:'项目总览',exact:true}).waitFor();
  await page.route('**/api/snapshot',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({ok:false,message:'测试：读取暂时失败'})}));await page.getByRole('button',{name:'刷新进展',exact:true}).click();await page.getByRole('heading',{name:'项目暂时不可用',exact:true}).waitFor();assert.equal(await page.getByRole('heading',{name:'主要成果',exact:true}).count(),0);assert(await page.locator('#diagnostic').isDisabled());pass('failed refresh removes old business facts');
  assert.equal(errors.length,0);fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,at:new Date().toISOString(),browser:browser.version(),project_id:before.project_id,revision:before.revision,authority_sha256_before:before.authority_file_sha256,authority_sha256_after:after.authority_file_sha256,assets,requirements:mappings,dimensions,checks,errors,scope:'Real Core navigation and unchanged-state proof; explicitly synthetic response tests; no remote synchronization or human approval'},null,2));
  console.log(JSON.stringify({passed:true,checks:checks.length,browser:browser.version(),output:out}));
 }finally{await browser.close();}
})().catch(e=>{fs.writeFileSync(path.join(out,'failure.txt'),e.stack);console.error(e);process.exitCode=1;});
