'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../dashboard/app.js');
function sample(){return {identity:{problem:{evaluation_mode:'historical_benchmark'}},objects:{},tasks:{},requirements:{},status:{requirements:{rows:[],questions:{}},current_task:null,blockers:[],next_action:'执行当前文件的论文与交付审计',submission:{ready:false,state:'checked',blockers:[],audit_id:null}}};}
function object(kind,status,extra={}){return {id:'record@1',kind,status,effective_status:status,is_current:true,payload:{question:'Q1'},current_errors:[],...extra};}
test('opaque run and project identifiers never become display names',()=>{assert.equal(ui.displayTitle(object('RunRecord','executed',{id:'RUN-bbafc358e568414b@1'})),'第1问的计算记录');assert.equal(ui.projectName({competition:'cumcm',problem:{problem_year:2018,letter:'B'},title:'abcdef1234567890'}),'2018年 · 全国大学生数学建模竞赛 · B题');});
test('interpretation record names do not label a resolved or historical choice as an open problem',()=>{
  for(const status of ['open','resolved'])for(const is_current of [true,false]){
    const record=object('AmbiguityEntry','frozen',{is_current,payload:{question:'Q1',status}});
    assert.equal(ui.displayTitle(record),'第1问 · 题意解释');
    assert.doesNotMatch(ui.displayTitle(record),/需要澄清|待明确|已验证正确/);
    assert.equal(record.payload.status,status);
  }
});
test('known submission blockers have factual Chinese descriptions',()=>{for(const [raw,expected] of [['Formal visual review requires a human reviewer','正式提交前，还需要人工检查论文排版。'],['Package has not entered awaiting_submission','提交材料还未进入待提交阶段。']])assert.equal(ui.plainText(raw),expected);assert.match(ui.plainText('Historical/research checks are not formal submission readiness'),/不能.*正式提交/);});
test('unknown states are never promoted to successful',()=>{assert.equal(ui.statusLabel('approved_somewhere'),'尚未确认');assert.equal(ui.isUsable(object('ResultRecord','executed')),false);assert.equal(ui.isUsable(object('ResultRecord','verified',{current_errors:['changed']})),false);});
test('run completion, check completion and submission stay distinct',()=>{assert.match(ui.statusLabel('executed'),/待检查/);assert.notEqual(ui.statusLabel('verified'),ui.statusLabel('completed'));assert.notEqual(ui.statusLabel('checked'),ui.statusLabel('submitted'));});
test('duplicate requirement descriptions do not shrink coverage',()=>{const v=sample();v.status.requirements.rows=[1,2,3].map(n=>({id:'REQ-Q1-'+n,question:'Q1',status:'verified',contract_current:true}));v.status.requirements.questions={Q1:'verified'};const [g]=ui.questionGroups(v);assert.equal(g.requirements.length,3);assert.equal(ui.questionProgress(g).label,'本问要求已核对');assert.equal(v.status.submission.ready,false);});
test('an omitted subquestion in requirement summary still appears from current objects',()=>{const v=sample();v.objects.other=object('ProblemContract','frozen',{payload:{question:'Q3'}});assert.deepEqual(ui.questionGroups(v).map(g=>g.name),['第3问']);assert.equal(ui.questionProgress(ui.questionGroups(v)[0]).label,'进度尚未完整记录');});
test('completed tasks alone never establish requirement verification',()=>{const v=sample();v.tasks['T-Q1']={id:'T-Q1',status:'completed'};v.objects.m=object('ModelSpec','frozen');const g=ui.questionGroups(v)[0];assert.notEqual(ui.questionProgress(g).label,'本问要求已核对');});
test('stale contract does not show verified coverage',()=>{const v=sample();v.status.requirements.rows=[{id:'req',question:'Q1',status:'verified',contract_current:false}];assert.equal(ui.questionProgress(ui.questionGroups(v)[0]).label,'部分内容需要重检');});
test('replaced historical records are not current blockers',()=>{const v=sample();v.objects.old=object('PaperSection','stale',{is_current:false});assert.equal(ui.currentProblems(v).length,0);assert.equal(ui.statusLabel('stale',v.objects.old),'旧版本');});
test('current file drift is still visible',()=>{const v=sample();v.objects.changed=object('ResultRecord','stale',{current_errors:['文件变化: RUN-bbafc358e568414b@1']});assert.equal(ui.currentProblems(v).length,1);assert.match(ui.plainText(v.objects.changed.current_errors[0]),/修改.*重新检查/);});
test('pending human review wins over repeating an already successful audit',()=>{const v=sample();v.objects.audit=object('DeliveryAudit','verified');v.status.submission.audit_id='audit';v.status.submission.blockers=['Formal visual review requires a human reviewer'];assert.deepEqual(ui.pendingConfirmations(v),v.status.submission.blockers);assert.equal(ui.nextAction(v),'正式提交前，还需要人工检查论文排版。');});
test('successful historical audit does not imply submission readiness',()=>{const v=sample();v.objects.audit=object('DeliveryAudit','verified');v.status.submission.audit_id='audit';assert.match(ui.nextAction(v),/剩余的提交条件/);assert.equal(v.status.submission.ready,false);});
test('no recorded approval need does not manufacture one',()=>{const v=sample();assert.deepEqual(ui.pendingConfirmations(v),[]);});
test('authority effective task state overrides old completed status',()=>{const v=sample();v.tasks['T-Q1']={id:'T-Q1',title:'检查数据',status:'completed',effective_status:'stale'};v.status.current_task=v.tasks['T-Q1'];assert.equal(ui.nextAction(v),'检查数据');});
test('unknown English explanation remains recognizable as untranslated',()=>{assert.equal(ui.plainText('new unsupported verification problem','请查看原文'),'请查看原文');});
test('mixed Chinese messages remove identifiers while retaining the message',()=>{const text=ui.plainText('请检查 RUN-bbafc358e568414b@1 和 12345678-abcd-1234-abcd-123456789abc');assert.match(text,/请检查/);assert.doesNotMatch(text,/bbaf|12345678|RUN-/);});
test('navigation stage is not used to infer progress or readiness',()=>{const v=sample();v.identity.navigation_stage=9;assert.deepEqual(ui.questionGroups(v),[]);assert.equal(v.status.submission.ready,false);});
test('algorithm names and reference identifiers remain meaningful',()=>{for(const value of ['基于 ARIMA-LSTM 的预测模型','采用 NSGA-II 比较候选方案','采用 t-test 比较均值','采用 T-test 比较均值','DOI 10.1234/abc-def 已核验','使用 leave-one-out 验证'])assert.equal(ui.plainText(value),value);});
test('similarly worded requirements retain distinct scenario context',()=>{const labels=[];for(const group of [1,2,3])for(const situation of ['single','two','fault'])labels.push(ui.requirementContext({source_anchor:`Problem B Task two, Table 1 parameter group ${group}; situation ${situation}`}));assert.equal(new Set(labels).size,9);assert.equal(labels[0],'第1组参数 · 单工序');assert.equal(labels[8],'第3组参数 · 故障情景');});
test('requirement output names preserve scenario and process distinctions',()=>{assert.equal(ui.outputLabel('group2_fault_two'),'第2组故障情景双工序结果');assert.notEqual(ui.outputLabel('group2_fault_two'),ui.outputLabel('group2_fault_single'));});
test('unknown requirement source never acquires an invented scenario',()=>{assert.equal(ui.requirementContext({source_anchor:'Something from another competition'}),'');});
test('task event descriptions translate event state rather than current task state',()=>{const tasks={'T-Q2':{id:'T-Q2',title:'检查结果',status:'completed'}};assert.equal(ui.changeDescription({reason:'任务 T-Q2 -> running'}, {}, tasks),'检查结果：进行中');assert.equal(ui.changeDescription({reason:'任务 T-Q2 -> completed'}, {}, tasks),'检查结果：已完成');});
test('registration events use record names without leaking projection keys',()=>{const records={'projection.Q2@1':object('ArtifactRecord','generated',{id:'projection.Q2@1',payload:{question:'Q2',artifact_type:'table',path:'paper/healthy.csv'}})};const label=ui.changeDescription({reason:'登记 ArtifactRecord projection.Q2',objects:['projection.Q2@1']},records);assert.match(label,/正常情景结果表/);assert.doesNotMatch(label,/projection|ArtifactRecord|@1/);});
test('current parameter entries take precedence over legacy parameters and retain source meaning',()=>{
  const current={parameter_id:'capacity',meaning:'储能装置额定容量',current_value:12000,unit:'kWh'};
  assert.deepEqual(ui.parameterRows({entries:[current],parameters:[{...current,current_value:99999}]}),[['储能装置额定容量','12000','千瓦时']]);
  assert.deepEqual(ui.parameterRows({entries:[],parameters:[current]}),[]);
  assert.deepEqual(ui.parameterRows({parameters:[current]}),[['储能装置额定容量','12000','千瓦时']]);
});
test('parameter values retain zero and false while missing complex or invalid values are explicit',()=>{
  const rows=ui.parameterRows({entries:[0,false,null,undefined,[1,2],{x:3},NaN].map(current_value=>({meaning:'测试参数',unit:'dimensionless',current_value}))});
  assert.deepEqual(rows.map(r=>r[1]),['0','否','尚未设置','尚未设置','复合取值（见诊断记录）','复合取值（见诊断记录）','无效数值，需检查']);
  assert(rows.every(r=>r[2]==='无量纲'));
});
test('unknown parameter meaning is not fabricated and internal identifiers stay out of parameter rows',()=>{
  const rows=ui.parameterRows({entries:[{parameter_id:'PARAM-secret',meaning:'Unknown external concept',current_value:1.23456789,unit:'kg/m³'},null,{meaning:'引用参数 PARAM-secret',current_value:'RUN-bbafc358e568414b@1',unit:''}]});
  assert.match(rows[0][0],/含义待补充/);assert.equal(rows[0][1],'1.23456789');assert.equal(rows[0][2],'kg/m³');
  assert.equal(rows[1][1],'尚未设置');assert.equal(rows[2][2],'单位未记录');assert.doesNotMatch(JSON.stringify(rows),/PARAM-secret|bbafc358e568414b/);
  assert.doesNotMatch(ui.parameterRows({entries:[{parameter_id:'capacity',meaning:'Battery capacity',current_value:12000,unit:'kWh'}]})[0][0],/通行能力/,'a parameter name must not be guessed from an unrelated metric dictionary');
});
