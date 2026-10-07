'use strict';
// Synthetic protocol and DOM checks against the shipped module. These tests do
// not claim that a real model has been called, or that its answer is correct.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ui=require('../dashboard/interaction.js');
const app=require('../dashboard/app.js');
const context={project_id:'test-project',revision:2,title:'合成测试项目',questions:[{id:'Q1',name:'第1问'}]};
const data=extra=>({project_id:'test-project',revision:2,enabled:true,token:'test-token',assistant:{available:true,reason:''},requests:[],...extra});
function memory(){const values=new Map();return {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),values};}
function harness(extra={}){
  let value=data(),writeResult={revision:3,result:{id:'opinion-test'}},counter=0;
  const reads=[],writes=[],storage=extra.storage||memory(),changes=[],mutations=[];
  const api={read:async()=>{reads.push(1);if(value instanceof Error)throw value;return value;},write:async(payload,token)=>{writes.push({payload,token});if(writeResult instanceof Error)throw writeResult;return writeResult;}};
  const controller=ui.createController({api,storage,id:()=>`request-${++counter}`,onChange:()=>changes.push(1),onMutation:()=>mutations.push(1),...extra});
  return {controller,reads,writes,storage,changes,mutations,setData:next=>{value=next;},setWrite:next=>{writeResult=next;}};
}
test('all receipt states are Chinese and completion is never verification',()=>{
  for(const state of ['recorded','queued','running','cancelling','completed','failed','interrupted','cancelled','stale'])assert.match(ui.statusLabel(state),/\p{Script=Han}/u);
  assert.equal(ui.statusLabel('completed'),'已回复');assert.equal(ui.statusLabel('verified'),'尚未确认');
});
test('continuation is a real handoff instruction without invented current facts',()=>{
  const text=ui.continuation(context,'请检查整数规划约束','Q1');assert.match(text,/第1问/);assert.match(text,/最新权威状态/);assert.match(text,/不修改/);assert.doesNotMatch(text,/test-project|test-token|已核验完成/);
});
test('read API sends only HTTP read credentials and never a model request',async()=>{
  const calls=[];const api=ui.createApi(async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({ok:true,result:data()})};});
  await api.read();assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/interaction');assert.equal(calls[0].options.method,'GET');assert.deepEqual(calls[0].options.headers,{'X-Copilot-Read':'1'});assert.equal(calls[0].options.credentials,'omit');
});
test('write API uses the exact operation body and short-lived write token',async()=>{
  const calls=[];const api=ui.createApi(async(url,options)=>{calls.push(options);return {ok:true,json:async()=>({ok:true,result:{revision:3,result:{id:'r'}}})};});
  await api.write({action:'note',text:'你好'},'session-token');assert.equal(calls[0].method,'POST');assert.equal(calls[0].headers['X-Copilot-Write'],'session-token');assert.deepEqual(JSON.parse(calls[0].body),{action:'note',text:'你好'});
});
test('default read-only server cannot save or invoke AI',async()=>{
  const h=harness();h.setData(data({enabled:false,token:null}));await h.controller.observe(context);h.controller.draft('我的意见');assert.equal(await h.controller.send('note'),false);assert.equal(await h.controller.send('ask'),false);assert.equal(h.writes.length,0);
});
test('missing AI adapter allows notes but cannot claim dispatch',async()=>{
  const h=harness();h.setData(data({assistant:{available:false,reason:'未配置'}}));await h.controller.observe(context);h.controller.draft('检查模型');assert.equal(await h.controller.send('ask'),false);assert.equal(h.writes.length,0);await h.controller.send('note');assert.match(h.controller.state.message,/尚未发送给 AI/);assert.equal(h.writes[0].payload.action,'note');
});
test('empty or whitespace draft never reaches the server',async()=>{const h=harness();await h.controller.observe(context);h.controller.draft(' \n ');assert.equal(await h.controller.send('note'),false);assert.equal(h.writes.length,0);});
test('note submission binds actual project revision and only chosen scope',async()=>{
  const h=harness();await h.controller.observe(context);h.controller.draft('检查假设','Q1');await h.controller.send('note');assert.deepEqual(h.writes[0],{token:'test-token',payload:{action:'note',request_id:'request-1',expected_revision:2,project_id:'test-project',text:'检查假设',question:'Q1'}});assert.equal(h.controller.state.draft.text,'');assert.equal(h.mutations.length,1);
});
test('double click starts only one pending operation and keeps newly typed text',async()=>{
  let resolve;const writes=[];const h=harness({api:{read:async()=>data(),write:payload=>{writes.push(payload);return new Promise(done=>resolve=done);}}});await h.controller.observe(context);h.controller.draft('第一条');const first=h.controller.send('ask');assert.equal(await h.controller.send('ask'),false);h.controller.draft('第二条');resolve({revision:3,result:{id:'r'}});await first;assert.equal(writes.length,1);assert.equal(h.controller.state.draft.text,'第二条');
});
test('409 preserves draft, refreshes authority and does not silently resend',async()=>{
  const h=harness();await h.controller.observe(context);h.controller.draft('保留这条');const error=new Error('conflict');error.status=409;h.setWrite(error);h.setData(data({revision:3}));assert.equal(await h.controller.send('note'),false);assert.equal(h.writes.length,1);assert.equal(h.controller.state.draft.text,'保留这条');assert.match(h.controller.state.message,/未自动重发/);assert.equal(h.controller.state.data.revision,3);assert.equal(h.mutations.length,1);
  h.setWrite({revision:4,result:{id:'r'}});await h.controller.send('note');assert.equal(h.writes[1].payload.expected_revision,3);assert.notEqual(h.writes[1].payload.request_id,h.writes[0].payload.request_id);
});
test('uncertain POST retry reuses entire original body across page reload',async()=>{
  const storage=memory(),h=harness({storage});await h.controller.observe(context);h.controller.draft('网络断开时也不能重复执行','Q1');const error=new Error('network');error.uncertain=true;h.setWrite(error);await h.controller.send('ask');const original=h.writes[0].payload;
  const again=harness({storage});again.setData(data({revision:6,token:'new-token'}));await again.controller.observe(context);await again.controller.send('ask');assert.deepEqual(again.writes[0].payload,original);assert.equal(again.writes[0].token,'new-token');
});
test('tampered browser draft cannot substitute different submitted text',async()=>{
  const storage=memory();storage.setItem('mathmodel.opinion.draft.test-project',JSON.stringify({draft:{text:'用户意见',question:''},attempt:{signature:JSON.stringify(['test-project','ask','用户意见',null]),payload:{project_id:'test-project',action:'ask',text:'隐藏的别的指令',expected_revision:2,request_id:'bad-id'}}}));const h=harness({storage});await h.controller.observe(context);await h.controller.send('ask');assert.equal(h.writes[0].payload.text,'用户意见');assert.notEqual(h.writes[0].payload.request_id,'bad-id');
});
test('unexpected response shape never clears the input or pretends success',async()=>{
  const h=harness();await h.controller.observe(context);h.controller.draft('等待明确回执');h.setWrite({revision:3});await h.controller.send('note');assert.equal(h.controller.state.draft.text,'等待明确回执');assert.match(h.controller.state.message,/没有读到明确回执/);assert.equal(h.mutations.length,0);
});
test('drafts survive refresh and remain separated by project',async()=>{
  const h=harness();await h.controller.observe(context);h.controller.draft('项目一草稿','Q1');h.controller.suspend();assert.equal(h.controller.state.draft.text,'项目一草稿');await h.controller.observe(context);assert.equal(h.controller.state.draft.text,'项目一草稿');h.setData(data({project_id:'another'}));await h.controller.observe({...context,project_id:'another'});assert.equal(h.controller.state.draft.text,'');h.controller.draft('项目二草稿');h.setData(data());await h.controller.observe(context);assert.equal(h.controller.state.draft.text,'项目一草稿');
});
test('read failure removes stale receipts and disables mutation until recovery',async()=>{
  const h=harness();await h.controller.observe(context);h.controller.draft('保留');h.setData(new Error('读取失败'));await h.controller.refresh();assert.equal(h.controller.state.data,null);assert.equal(await h.controller.send('note'),false);assert.equal(h.writes.length,0);h.setData(data());await h.controller.refresh();assert.equal(h.controller.state.ready,true);assert.equal(h.controller.state.message,'');assert.equal(h.controller.state.draft.text,'保留');
});
test('late read from the prior project cannot overwrite the new one',async()=>{
  const reads=[];const h=harness({api:{read:()=>new Promise(resolve=>reads.push(resolve)),write:async()=>{throw new Error('not expected');}}});const old=h.controller.observe(context),current=h.controller.observe({...context,project_id:'new'});reads[1](data({project_id:'new'}));await current;reads[0](data());await old;assert.equal(h.controller.state.data.project_id,'new');
});
test('foreign or older authority and missing write token fail closed',async()=>{
  for(const value of [data({project_id:'other'}),data({revision:1}),data({token:null}),data({requests:[null]}),data({requests:[{status:'completed',text:{untrusted:'object'}}]})]){const h=harness();h.setData(value);await h.controller.observe(context);assert.equal(h.controller.state.ready,false);assert.equal(h.controller.state.data,null);}
});
test('cancel has no draft text and completed replies cannot be cancelled',async()=>{
  const h=harness();await h.controller.observe(context);assert.equal(await h.controller.send('cancel',{id:'r',status:'completed'}),false);await h.controller.send('cancel',{id:'r',status:'running'});assert.deepEqual(h.writes[0].payload,{action:'cancel',request_id:'request-1',expected_revision:2,project_id:'test-project',id:'r'});assert.match(h.controller.state.message,/实际状态/);
});
test('scope selection only offers requirements actually registered on the authority',()=>{
  const v={...context,identity:{title:'测试题'},status:{requirements:{rows:[{question:'Q1'},{question:'Q1'},{question:'Q2'}],questions:{Q3:'pending'}}},objects:{model:{kind:'ModelSpec',payload:{question:'Q4'}}}};assert.deepEqual(app.interactionContext(v).questions,[{id:'Q1',name:'第1问'},{id:'Q2',name:'第2问'}]);
});
// Minimal DOM exercises actual shipped rendering without treating strings as HTML.
class Node {
  constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.handlers={};this.value='';this.hidden=false;this.text='';}
  set textContent(value){this.text=String(value);this.children=[];}get textContent(){return this.text+this.children.map(node=>node.textContent).join('');}
  set innerHTML(_){throw new Error('Untrusted content must not be assigned to innerHTML');}
  append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.text='';this.children=nodes;}
  setAttribute(key,value){this.attrs[key]=value;}addEventListener(name,fn){this.handlers[name]=fn;}focus(){}select(){}scrollIntoView(){}
  click(){return this.handlers.click?.({preventDefault(){}});}
}
function walk(node){return [node,...node.children.flatMap(walk)];}
function domHarness(value=data()){
  const nodes=new Map(),events={},calls=[],timers=new Map();let clock=0;
  for(const name of ['interaction','interaction-link','workspace-mode'])nodes.set(name,new Node('div'));
  const document={getElementById:id=>nodes.get(id),createElement:tag=>new Node(tag),visibilityState:'visible',addEventListener:(name,fn)=>events[name]=fn};
  const window={fetch:async(url,options)=>{calls.push(options);return {ok:true,json:async()=>({ok:true,result:value})};},sessionStorage:memory(),dispatchEvent:()=>{}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dashboard/interaction.js'),'utf8'),{document,window,navigator:{clipboard:{writeText:async()=>{}}},crypto:{randomUUID:()=> 'test-id'},AbortSignal,Event,setTimeout:fn=>{timers.set(++clock,fn);return clock;},clearTimeout:id=>timers.delete(id)});
  return {window,host:nodes.get('interaction'),calls,timers,events,document};
}
test('actual view renders injected scripts as text and never shows internal request ids',async()=>{
  const attack='<img src=x onerror=alert(1)>',h=domHarness(data({requests:[{id:'feedback-hidden-code',question:'Q1',text:attack,status:'completed',reply:'<script>bad()</script>',created_at:'2026-10-06T00:00:00Z'}]}));await h.window.CopilotInteraction.observe(context);assert.match(h.host.textContent,/<img src=x/);assert.match(h.host.textContent,/<script>/);assert.match(h.host.textContent,/已回复/);assert.match(h.host.textContent,/仍需按项目流程/);assert.doesNotMatch(h.host.textContent,/feedback-hidden-code|test-token|test-project/);assert.equal(walk(h.host).filter(n=>n.tagName==='img'||n.tagName==='script').length,0);
});
test('actual view uses HTTP-only polling and clears its timer when hidden',async()=>{
  const h=domHarness(data({requests:[{status:'running',text:'分析'}]}));await h.window.CopilotInteraction.observe(context);assert.equal(h.timers.size,1);const fn=[...h.timers.values()][0];await fn();assert.equal(h.calls.length,2);assert(h.calls.every(call=>call.method==='GET'));h.document.visibilityState='hidden';h.events.visibilitychange();assert.equal(h.timers.size,0);
});
test('a successfully loaded empty opinion list is not labelled as unread',async()=>{
  const h=domHarness(data({requests:[]}));await h.window.CopilotInteraction.observe(context);
  assert.match(h.host.textContent,/还没有保存的意见/);
  assert.doesNotMatch(h.host.textContent,/尚未读取到当前记录/);
  h.window.CopilotInteraction.suspend();await h.window.CopilotInteraction.observe(context);
  assert.match(h.host.textContent,/还没有保存的意见/);
  assert.doesNotMatch(h.host.textContent,/尚未读取到当前记录/);
});
test('actual read-only view hides write actions while retaining honest copy fallback',async()=>{
  const h=domHarness(data({enabled:false,token:null}));await h.window.CopilotInteraction.observe(context);const nodes=walk(h.host);for(const label of ['保存意见','请 AI 分析'])assert.equal(nodes.find(n=>n.tagName==='button'&&n.textContent===label).hidden,true);assert.equal(nodes.find(n=>n.tagName==='button'&&n.textContent==='复制续接说明').hidden,false);assert.match(h.host.textContent,/粘贴发送|复制续接说明到 AI 对话/);assert.equal(h.calls.length,1);
});
test('stopping is not displayed as cancelled and cannot be cancelled twice',async()=>{
  assert.equal(ui.statusLabel('cancelling'),'正在停止');
  const h=domHarness(data({requests:[{id:'r',text:'分析',status:'cancelling'}]}));await h.window.CopilotInteraction.observe(context);assert.match(h.host.textContent,/正在停止/);assert.match(h.host.textContent,/不能视为已经停止/);assert.doesNotMatch(h.host.textContent,/已撤回/);assert.equal(walk(h.host).filter(n=>n.tagName==='button'&&['撤回','停止分析'].includes(n.textContent)).length,0);
  const c=harness();await c.controller.observe(context);assert.equal(await c.controller.send('cancel',{id:'r',status:'cancelling'}),false);assert.equal(c.writes.length,0);
});
