const test=require('node:test'),assert=require('node:assert/strict');
const ui=require('../dashboard/app.js');

test('long and tabular claims have a compact label and keep full stored text',()=>{
  const claim='计算结果如下。\n|日期|数值|\n|--|--|\n|2026-01-01|3.202770083102493|';
  const obj={id:'claim@1',kind:'EvidenceMapEntry',payload:{question:'Q1',claim}};
  assert.equal(ui.displayTitle(obj),'第1问 · 论文结论（展开查看完整内容）');
  assert.equal(obj.payload.claim,claim);
  obj.payload.claim='a'.repeat(121);assert.match(ui.displayTitle(obj),/展开查看完整内容/);
});
test('changed source is linked from stale descendants using actual versions and file observation',()=>{
  const objects={
    old:{id:'old',kind:'ParameterSet',key:'p',is_current:false,dependencies:[]},
    new:{id:'new',kind:'ParameterSet',key:'p',is_current:true,dependencies:[]},
    code:{id:'code',kind:'CodeManifest',is_current:true,files:[{path:'solver.py',sha256:'old-hash'}]},
    run:{id:'run',kind:'RunRecord',is_current:true,effective_status:'stale',dependencies:['old','code']},
    claim:{id:'claim',kind:'EvidenceMapEntry',is_current:true,effective_status:'stale',dependencies:['run']},
    other:{id:'other',kind:'ResultRecord',is_current:true,effective_status:'verified',dependencies:[]}
  };
  const v={objects,observed_files:{'solver.py':{sha256:'new-hash'}}};
  const before=JSON.stringify(v),g=ui.recheckGuide(objects.run,v);
  assert(g.causes.some(x=>x.id==='old'&&x.latest==='new'&&x.message.includes('参数设置')));
  assert(g.causes.some(x=>x.id==='code'&&x.type==='file'));
  assert.deepEqual(g.downstream,['claim']);assert(!g.downstream.includes('other'));
  assert.equal(JSON.stringify(v),before);
  assert.equal(ui.recheckGuide(objects.old,v),null);
  assert.equal(ui.recheckGuide(objects.other,v),null);
});
test('unexplained invalidity does not invent a changed parameter or file',()=>{
  const object={id:'x',effective_status:'stale',dependencies:['missing']};
  assert.deepEqual(ui.recheckGuide(object,{objects:{}}).causes,[]);
});
test('identical observed SHA-256 with a different letter case is not file drift',()=>{
  const object={id:'x',effective_status:'stale',files:[{path:'solver.py',sha256:'ABCDEF123'}]};
  assert.deepEqual(ui.recheckGuide(object,{objects:{},observed_files:{'solver.py':{sha256:'abcdef123'}}}).causes,[]);
});
test('metric help preserves missing semantics and only copies a request',()=>{
  const obj={id:'result.Q1@1',metric_details:{items:[{metric_path:'/price',value:12.345,label:null,unit:null,scope:null,declaration_status:'missing',metadata_source_ids:[]}]}};
  const before=JSON.stringify(obj),request=ui.metricHelpRequest(obj);
  assert(request.includes('/price'));assert(request.includes('不要从字段名猜测'));assert(request.includes('重跑'));
  assert(!request.includes('元'));assert.equal(before,JSON.stringify(obj));
  obj.metric_details.items[0]={label:'已声明指标',unit:'m',scope:'示例范围',declaration_status:'declared'};
  assert.equal(ui.metricHelpRequest(obj),null);
});
