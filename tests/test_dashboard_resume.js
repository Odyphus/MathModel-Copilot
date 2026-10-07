'use strict';
// Behavioral tests with a minimal DOM and explicitly synthetic observations.
// This exercises the shipped app; it does not establish browser visual acceptance.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../dashboard/app.js'),'utf8');
class Events {
  constructor(){this.listeners={};}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  fire(type,extra={}){for(const fn of this.listeners[type]||[])fn({type,target:this,currentTarget:this,...extra});}
}
class Element extends Events {
  constructor(tag){super();this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.text='';this.className='';this.open=false;this.disabled=false;this.parentElement=null;this.root=false;this.scrollTop=0;this.classList={add:value=>{this.className+=' '+value;}};}
  get isConnected(){return this.root||Boolean(this.parentElement?.isConnected);}
  detachChildren(){for(const node of this.children)node.parentElement=null;this.children=[];}
  set textContent(value){this.text=String(value);this.detachChildren();}
  get textContent(){return this.text+this.children.map(x=>x.textContent).join('');}
  append(...nodes){for(const node of nodes){node.parentElement=this;this.children.push(node);}}
  prepend(...nodes){for(const node of nodes)node.parentElement=this;this.children.unshift(...nodes);}
  replaceChildren(...nodes){this.text='';this.detachChildren();this.append(...nodes);}
  setAttribute(key,value){this.attributes[key]=value;}
  getAttribute(key){return this.attributes[key]??null;}
  removeAttribute(key){delete this.attributes[key];}
  get lastChild(){return this.children.at(-1);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  querySelectorAll(selector){return walk(this).slice(1).filter(node=>matches(node,selector));}
  closest(selector){let node=this;while(node){if(matches(node,selector))return node;node=node.parentElement;}return null;}
  contains(node){return walk(this).includes(node);}
  focus(){if(this.ownerDocument)this.ownerDocument.activeElement=this;}
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
  scrollIntoView(){}
  showModal(){this.open=true;}
  close(){this.open=false;this.fire('close');}
  click(){if(!this.disabled)this.fire('click');}
}
function walk(node){return [node,...node.children.flatMap(walk)];}
function matches(node,selector){
  return selector.split(',').some(part=>{
    if(part.startsWith('.'))return node.className.split(' ').includes(part.slice(1));
    if(part.startsWith('#'))return node.id===part.slice(1);
    const attribute=part.match(/^\[data-([a-z-]+)(?:="([^"]*)")?\]$/);
    if(attribute){const key=attribute[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return attribute[2]===undefined?Object.hasOwn(node.dataset,key):node.dataset[key]===attribute[2];}
    return node.tagName===part;
  });
}
const sha=seed=>Number(seed).toString(16).padStart(64,'0');
const clone=value=>JSON.parse(JSON.stringify(value));
function storage(){
  const data=new Map(),writes=[];
  return {data,writes,getItem:key=>data.get(key)??null,setItem:(key,value)=>{data.set(key,value);writes.push({key,value});}};
}
function timers(){
  const pending=new Map();let id=0;
  return {pending,setTimeout:(fn,delay)=>{const token=++id;pending.set(token,{fn,delay});return token;},clearTimeout:token=>pending.delete(token),
    run:delay=>{const jobs=[...pending].filter(([,job])=>job.delay===delay);for(const [token,job] of jobs){pending.delete(token);job.fn();}return jobs.length;}};
}
function observation(revision=1,entries=[{parameter_id:'capacity',meaning:'电池容量',current_value:12000,unit:'kWh'}]){
  const id='params.Q1@1';
  return {read_only:true,project_id:'synthetic-test-project',revision,state_hash:sha(revision),file_observation_hash:sha(100),snapshot_id:'snapshot-'+revision,authority_file_sha256:sha(200+revision),observed_files:{},checked_at:'2026-10-06T00:00:00Z',identity:{title:'测试项目',problem:{evaluation_mode:'historical_benchmark'}},objects:{[id]:{id,key:'parameters.Q1',kind:'ParameterSet',status:'frozen',is_current:true,payload:{question:'Q1',entries}}},tasks:{},requirements:{},status:{requirements:{rows:[],questions:{Q1:'pending'}},blockers:[],submission:{ready:false,state:'unknown',blockers:[]}}};
}
function harness({saved=storage(),hash='#questions'}={}){
  const nodes=[];
  const document=new Events();document.visibilityState='visible';document.hasFocus=()=>true;
  document.createElement=tag=>{const node=new Element(tag);node.ownerDocument=document;nodes.push(node);return node;};
  document.createElementNS=(_,tag)=>document.createElement(tag);
  document.getElementById=id=>{let node=nodes.find(n=>n.id===id&&n.isConnected);if(!node){node=document.createElement('div');node.id=id;node.root=true;}return node;};
  document.querySelector=selector=>nodes.find(node=>node.isConnected&&matches(node,selector))||null;
  const window=new Events(),requests=[],fileRequests=[],clock=timers();window.localStorage=saved;window.scrollY=0;window.scrollTo=options=>{window.scrollY=options.top;};
  window.CopilotWorkbench=require('../dashboard/workbench.js');
  window.CopilotData={load:()=>new Promise((resolve,reject)=>requests.push({resolve,reject})),readFile:(view,path)=>new Promise((resolve,reject)=>fileRequests.push({view,path,resolve,reject}))};
  const location={hash},history={replaceState:(_,__,hash)=>{location.hash=hash;}};
  vm.runInNewContext(source,{document,window,location,history,Node:Element,setTimeout:clock.setTimeout,clearTimeout:clock.clearTimeout,URL,Blob,console});
  const settle=async(index,value)=>{requests[index].resolve(value);await new Promise(resolve=>setImmediate(resolve));};
  const fail=async(index)=>{requests[index].reject(new Error('本地读取失败'));await new Promise(resolve=>setImmediate(resolve));};
  const settleFile=async(index,value)=>{fileRequests[index].resolve(value);await new Promise(resolve=>setImmediate(resolve));};
  const content=()=>document.getElementById('content').textContent;
  const openParameters=()=>{const link=walk(document.getElementById('content')).find(n=>n.dataset.objectId==='params.Q1@1');assert(link,'parameter record is reachable');link.click();return document.getElementById('detail-body').textContent;};
  const findButton=(text,root=document.getElementById('content'))=>walk(root).find(node=>node.tagName==='button'&&node.textContent===text);
  const detail=()=>document.getElementById('detail-body').textContent;
  const reload=()=>document.getElementById('refresh').click();
  const navigate=page=>document.getElementById('nav-'+page).click();
  return {document,window,requests,fileRequests,settle,settleFile,fail,content,detail,openParameters,findButton,reload,navigate,saved,clock,location};
}
test('canonical ParameterSet entries appear with meaning value and unit in the actual detail reader',async()=>{
  const h=harness();await h.settle(0,observation());const text=h.openParameters();
  assert.match(text,/当前参数/);assert.match(text,/电池容量/);assert.match(text,/12000/);assert.match(text,/千瓦时/);assert.doesNotMatch(text,/params\.Q1|parameter_id/);
});
test('returning preserves the detail and replaces old values after rechecking',async()=>{
  const h=harness();await h.settle(0,observation());h.openParameters();
  h.document.visibilityState='hidden';h.document.fire('visibilitychange');assert.equal(h.requests.length,1);
  h.document.visibilityState='visible';h.document.fire('visibilitychange');h.window.fire('focus');
  assert.equal(h.requests.length,2,'one read for the paired return events');assert.equal(h.document.getElementById('detail').open,true);assert.match(h.document.getElementById('detail-refresh-status').textContent,/暂保留上次读取/);
  await h.settle(1,observation(2,[{meaning:'电池容量',current_value:18000,unit:'kWh'}]));
  const text=h.document.getElementById('detail-body').textContent;assert.match(text,/18000/);assert.doesNotMatch(text,/12000/);assert.equal(h.document.getElementById('detail').open,true);
});
test('return from another application refreshes even if the browser tab stayed visible',async()=>{
  const h=harness();await h.settle(0,observation());h.window.fire('blur');h.window.fire('focus');assert.equal(h.requests.length,2);await h.settle(1,observation(2));
  h.window.fire('focus');assert.equal(h.requests.length,2,'focus without a preceding departure does not poll');
});
test('late response started before departure cannot replace the returned current observation',async()=>{
  const h=harness();h.document.visibilityState='hidden';h.document.fire('visibilitychange');h.document.visibilityState='visible';h.document.fire('visibilitychange');assert.equal(h.requests.length,2);
  await h.settle(1,observation(2,[{meaning:'电池容量',current_value:18000,unit:'kWh'}]));await h.settle(0,observation());
  assert.match(h.openParameters(),/18000/);assert.doesNotMatch(h.openParameters(),/12000/);
});
test('a failed automatic refresh removes previous facts and can recover by returning again',async()=>{
  const h=harness();await h.settle(0,observation());h.window.fire('blur');h.window.fire('focus');assert.equal(h.requests.length,2);await h.fail(1);
  assert.match(h.content(),/项目暂时不可用/);assert.doesNotMatch(h.content(),/12000|第1问的参数设置/);assert.equal(h.document.getElementById('diagnostic').disabled,true);
  h.window.fire('blur');h.window.fire('focus');await h.settle(2,observation(3));assert.match(h.openParameters(),/12000/);
});
test('back-forward cache restore refreshes and initial pageshow does not duplicate startup loading',async()=>{
  const h=harness();h.window.fire('pageshow',{persisted:false});assert.equal(h.requests.length,1);await h.settle(0,observation());h.window.fire('pageshow',{persisted:true});assert.equal(h.requests.length,2);await h.settle(1,observation(2));
});
test('actual result detail shows declared meaning units and linked numeric provenance without traffic defaults',async()=>{
  const v=observation(),h=harness();
  v.objects.result={id:'result',kind:'ResultRecord',status:'verified',is_current:true,payload:{question:'Q1',metrics:{capacity:12000,horizon:24},scope:'合成储能案例'},dependencies:['run','check'],files:[],metric_details:{items:[{metric_path:'/capacity',value:12000,label:'储能容量',unit:'kWh',scope:'当前工况',metadata_source_ids:[],declaration_status:'declared'},{metric_path:'/horizon',value:24,label:'预测跨度',unit:'h',metadata_source_ids:[],declaration_status:'declared'}]}};
  v.objects.run={id:'run',kind:'RunRecord',status:'verified',is_current:true,payload:{question:'Q1'},dependencies:[],files:[]};
  v.objects.check={id:'check',kind:'ValidationReport',status:'verified',is_current:true,payload:{question:'Q1',checks:[{check_id:'capacity',status:'pass',criterion:'容量必须满足题设约束',predeclared:true,actual:12000,evidence:[]}]},dependencies:['run'],files:[]};
  await h.settle(0,v);walk(h.document.getElementById('content')).find(n=>n.dataset.objectId==='result').click();let detail=h.document.getElementById('detail-body');
  assert.match(detail.textContent,/储能容量/);assert.match(detail.textContent,/kWh/);assert.match(detail.textContent,/预测跨度/);assert.doesNotMatch(detail.textContent,/车辆当量|计算时长（秒）/);assert.match(detail.textContent,/数字来源与检查依据/);assert.match(detail.textContent,/不表示自然语言推论/);
  assert(walk(detail).some(n=>n.dataset.objectId==='run'));walk(detail).find(n=>n.dataset.objectId==='check').click();detail=h.document.getElementById('detail-body');assert.match(detail.textContent,/运行前已声明的标准/);assert.match(detail.textContent,/容量必须满足题设约束/);assert.match(detail.textContent,/12000/);
});
test('actual decision list shows recorded reasons without treating actor as authenticated approval',async()=>{
  const h=harness(),v=observation();v.decisions=[{decision:'保留线性规划基线',reason:'先建立可复核对照',actor:'human-admin',at:'2026-10-06T00:00:00Z',evidence:[]}];await h.settle(0,v);h.document.getElementById('changes-link').click();assert.match(h.content(),/已记录的项目决策/);assert.match(h.content(),/保留线性规划基线/);assert.match(h.content(),/先建立可复核对照/);assert.match(h.content(),/未经身份认证/);assert.doesNotMatch(h.content(),/已获人工批准|已自动采用/);
});

test('return summary survives a page reload and only explicit reading acknowledgement advances its cursor',async()=>{
  const saved=storage(),first=harness({saved,hash:'#overview'}),v1=observation();
  await first.settle(0,v1);assert.equal(saved.writes.length,1);assert.doesNotMatch(first.content(),/自上次已读后的变化/);
  const v2=observation(2,[{meaning:'电池容量',current_value:18000,unit:'kWh'}]);
  const second=harness({saved,hash:'#overview'});await second.settle(0,v2);
  assert.match(second.content(),/自上次已读后的变化/);assert.match(second.content(),/项目内容有更新/);
  assert.equal(saved.writes.length,1,'returning and rendering do not mark updates as read');
  second.reload();await second.settle(1,clone(v2));assert.match(second.content(),/自上次已读后的变化/);assert.equal(saved.writes.length,1);
  const authority=JSON.stringify(v2);second.findButton('这批变化已看过').click();
  assert.equal(saved.writes.length,2);assert.equal(JSON.parse(saved.writes[1].value).revision,2);
  assert.equal(JSON.stringify(v2),authority,'acknowledgement never mutates the authority snapshot');
  assert.doesNotMatch(second.content(),/自上次已读后的变化/);assert.equal(second.requests.length,2,'acknowledgement does not make a business API request');
  const third=harness({saved,hash:'#overview'});await third.settle(0,clone(v2));assert.doesNotMatch(third.content(),/自上次已读后的变化/);
  const v3=observation(3);third.reload();await third.settle(1,v3);assert.match(third.content(),/自上次已读后的变化/);
});

test('same-revision file drift updates both the cumulative summary and an open detail',async()=>{
  const h=harness({hash:'#overview'}),v1=observation();await h.settle(0,v1);h.navigate('questions');h.openParameters();h.navigate('overview');
  const v2=clone(v1);v2.file_observation_hash=sha(777);v2.snapshot_id='changed-file';
  v2.objects['params.Q1@1'].effective_status='stale';v2.objects['params.Q1@1'].current_errors=['参数来源文件已变化'];
  h.reload();await h.settle(1,v2);
  assert.equal(v2.revision,v1.revision);assert.match(h.content(),/自上次已读后的变化/);assert.match(h.content(),/需要重检/);
  assert.match(h.detail(),/相关文件已被修改，需要重新检查后再使用/);assert.equal(h.document.getElementById('detail').open,true);
  assert.match(h.document.getElementById('detail-refresh-status').textContent,/已重新核对/);
});

test('same-revision unclassified file change still gives a generic change notice',async()=>{
  const h=harness({hash:'#overview'}),v=observation();await h.settle(0,v);const next=clone(v);next.file_observation_hash=sha(778);
  h.reload();await h.settle(1,next);assert.match(h.content(),/还有其他记录或文件变化/);
});

test('an open current object follows its replacement version instead of keeping historical values',async()=>{
  const h=harness(),v1=observation();await h.settle(0,v1);h.openParameters();
  const v2=observation(2);v2.objects['params.Q1@1'].is_current=false;
  v2.objects['params.Q1@2']={...clone(v2.objects['params.Q1@1']),id:'params.Q1@2',is_current:true,payload:{question:'Q1',entries:[{meaning:'电池容量',current_value:22000,unit:'kWh'}]}};
  h.reload();await h.settle(1,v2);
  assert.equal(h.document.getElementById('detail').open,true);assert.match(h.detail(),/22000/);assert.doesNotMatch(h.detail(),/12000|旧版本/);
});

test('deleted detail content is withdrawn and back navigation cannot resurrect it',async()=>{
  const h=harness();await h.settle(0,observation());h.openParameters();
  const v2=observation(2);v2.objects={};h.reload();await h.settle(1,v2);
  assert.match(h.detail(),/这项记录暂不可用/);assert.doesNotMatch(h.detail(),/12000|当前参数/);
  assert.equal(h.document.getElementById('detail-back').disabled,true);h.document.getElementById('detail-back').click();assert.doesNotMatch(h.detail(),/12000/);
});

test('failed recheck closes the detail and removes the old numbers',async()=>{
  const h=harness();await h.settle(0,observation());h.openParameters();h.reload();await h.fail(1);
  assert.equal(h.document.getElementById('detail').open,false);assert.equal(h.detail(),'');assert.doesNotMatch(h.content(),/12000/);
});

test('switching projects closes the old detail and isolates the local reading cursor',async()=>{
  const h=harness();await h.settle(0,observation());h.openParameters();
  const v2=observation(2);v2.project_id='another-project';v2.identity.title='另一项目';v2.objects={};h.reload();await h.settle(1,v2);
  assert.equal(h.document.getElementById('detail').open,false);assert.match(h.document.getElementById('workspace-name').textContent,/另一项目/);
  assert.equal(h.saved.data.size,2);assert.equal(JSON.parse(h.saved.data.get('mathmodel.reading.v1:another-project')).revision,2);
  h.navigate('overview');assert.doesNotMatch(h.content(),/自上次已读后的变化|12000/);
});

function linkedObservation(revision=1,value=12000){
  const v=observation(revision,[{meaning:'电池容量',current_value:value,unit:'kWh'}]);
  v.objects['params.Q1@1'].dependencies=['model'];
  v.objects.model={id:'model',key:'model.Q1',kind:'ModelSpec',status:'frozen',is_current:true,payload:{question:'Q1',solver:{method:'线性规划'}}};
  return v;
}
function openLinkedModel(h){h.openParameters();const link=walk(h.document.getElementById('detail-body')).find(n=>n.dataset.objectId==='model');assert(link);link.click();assert.match(h.detail(),/采用的方法/);}

test('detail back navigation resolves the latest objects after a background refresh',async()=>{
  const h=harness();await h.settle(0,linkedObservation());openLinkedModel(h);h.reload();await h.settle(1,linkedObservation(2,28000));
  h.document.getElementById('detail-back').click();assert.match(h.detail(),/28000/);assert.doesNotMatch(h.detail(),/12000/);
  assert.equal(h.document.getElementById('detail-back').disabled,true);
});

test('clicking back while rechecking does not prematurely pop the detail history',async()=>{
  const h=harness();await h.settle(0,linkedObservation());openLinkedModel(h);h.reload();h.document.getElementById('detail-back').click();
  assert.match(h.detail(),/采用的方法/);await h.settle(1,linkedObservation(2,29000));
  assert.equal(h.document.getElementById('detail-back').disabled,false,'the previous detail remains in the history');
  h.document.getElementById('detail-back').click();assert.match(h.detail(),/29000/);assert.doesNotMatch(h.detail(),/12000/);
});

test('navigation during an unchanged response renders the newly requested page',async()=>{
  const h=harness(),v=observation();await h.settle(0,v);h.reload();h.navigate('paper');
  assert.equal(h.location.hash,'#paper');await h.settle(1,clone(v));
  assert.match(h.content(),/^论文准备/);assert.equal(h.document.getElementById('nav-paper').getAttribute('aria-current'),'page');
  assert.equal(h.document.getElementById('nav-questions').getAttribute('aria-current'),null);
});

test('changed observations preserve expanded sections, scroll and result search state',async()=>{
  const h=harness();await h.settle(0,observation());
  const disclosure=walk(h.document.getElementById('content')).find(n=>n.tagName==='details'&&n.querySelector('summary')?.textContent==='方案、假设与数据');
  assert(disclosure);disclosure.open=true;h.document.getElementById('content').scrollTop=125;h.window.scrollY=540;
  h.reload();await h.settle(1,observation(2));
  const replaced=walk(h.document.getElementById('content')).find(n=>n.tagName==='details'&&n.querySelector('summary')?.textContent==='方案、假设与数据');
  assert.equal(replaced.open,true);assert.equal(h.document.getElementById('content').scrollTop,125);assert.equal(h.window.scrollY,540);
  h.navigate('results');const input=walk(h.document.getElementById('content')).find(n=>n.tagName==='input');input.value='第1问';input.fire('input');input.focus();input.setSelectionRange(1,2);
  h.reload();await h.settle(2,observation(3));const updated=walk(h.document.getElementById('content')).find(n=>n.tagName==='input');
  assert.equal(updated.value,'第1问');assert.equal(h.document.activeElement,updated);assert.equal(updated.selectionStart,1);assert.equal(updated.selectionEnd,2);
});

function fileObservation(revision=1){const v=linkedObservation(revision);v.objects['params.Q1@1'].files=[{path:'note.md',byte_size:12}];return v;}
function startFile(h){h.openParameters();const button=h.findButton('查看内容',h.document.getElementById('detail-body'));assert(button);button.click();assert.equal(h.fileRequests.length,1);}

test('a bound-file response started before rechecking cannot refill the refreshed reader',async()=>{
  const h=harness();await h.settle(0,fileObservation());startFile(h);h.reload();
  assert.doesNotMatch(h.detail(),/正在检查并读取文件/);await h.settle(1,fileObservation(2));
  await h.settleFile(0,{content:'过期文件正文',current_errors:{}});assert.doesNotMatch(h.detail(),/过期文件正文/);
});

test('an old file response cannot fill a detail detached by opening another record',async()=>{
  const h=harness();await h.settle(0,fileObservation());startFile(h);
  walk(h.document.getElementById('detail-body')).find(n=>n.dataset.objectId==='model').click();assert.match(h.detail(),/采用的方法/);
  await h.settleFile(0,{content:'旧详情的文件正文',current_errors:{}});assert.doesNotMatch(h.detail(),/旧详情的文件正文/);
});

test('an unchanged refresh still cancels a pending old file response',async()=>{
  const h=harness(),v=fileObservation();await h.settle(0,v);startFile(h);h.reload();await h.settle(1,clone(v));
  await h.settleFile(0,{content:'不应回填的旧请求正文',current_errors:{}});
  assert.doesNotMatch(h.detail(),/不应回填的旧请求正文|正在检查并读取文件/);assert.match(h.detail(),/重新打开文件/);
});

test('visible polling pauses while hidden and resumes with one current observation',async()=>{
  const h=harness();await h.settle(0,observation());assert.equal(h.clock.run(15000),1);assert.equal(h.requests.length,2);await h.settle(1,observation(2));
  h.document.visibilityState='hidden';h.document.fire('visibilitychange');assert.equal(h.clock.run(15000),0);assert.equal(h.requests.length,2);
  h.document.visibilityState='visible';h.document.fire('visibilitychange');h.window.fire('focus');assert.equal(h.requests.length,3);
  await h.settle(2,observation(3));assert.equal(h.clock.run(15000),1);assert.equal(h.requests.length,4);await h.settle(3,observation(4));
});

test('disabled browser storage does not block the project and explicitly limits later comparison',async()=>{
  const denied={getItem(){throw new Error('storage disabled');},setItem(){throw new Error('storage disabled');}};
  const h=harness({saved:denied,hash:'#overview'});await h.settle(0,observation());assert.match(h.content(),/项目总览/);
  h.reload();await h.settle(1,observation(2));assert.match(h.content(),/浏览器未允许保存阅读标记/);
  h.findButton('这批变化已看过').click();assert.doesNotMatch(h.content(),/自上次已读后的变化/);
});

test('forged stored prose is not shown as current facts or a previously verified result',async()=>{
  const saved=storage(),cursor=require('../dashboard/workbench.js').makeVisit(observation());cursor.text='全部数学结果已验证：伪造摘要';
  saved.data.set('mathmodel.reading.v1:synthetic-test-project',JSON.stringify(cursor));
  const h=harness({saved,hash:'#overview'});await h.settle(0,observation(2));assert.doesNotMatch(h.content(),/伪造摘要|全部数学结果已验证|自上次已读后的变化/);
  assert.equal(JSON.parse(saved.writes.at(-1).value).revision,2);
});
