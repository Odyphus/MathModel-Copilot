'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ui = require('../dashboard/workbench.js');
const sha = char => char.repeat(64);
const copy = value => JSON.parse(JSON.stringify(value));
function view() {
  return {project_id: 'synthetic-project', revision: 3, state_hash: sha('a'), file_observation_hash: sha('b'),
    checked_at: '2026-10-06T12:00:00.123456+00:00', observed_files: {},
    objects: {result: {id: 'result', kind: 'ResultRecord', is_current: true, status: 'verified',
      payload: {question: 'Q1', metrics: {cost: 123456.789}}, current_errors: [], files: []}},
    tasks: {task: {id: 'task', title: '私人工作说明', status: 'running', current_errors: {}}},
    requirements: {req: {active: true, question: 'Q1', definition: {outputs: ['私人输出名称']}}},
    status: {interpretations: [], requirements: {rows: [{id: 'req', status: 'verified', contract_current: true}]}}};
}
function interpretation(id, kind, status, severity = 'medium', extra = {}) {
  return {object_id: id, kind, status, question: 'Q1', payload: {severity, statement: '当前状态里的说明'},
    current_errors: [], freeze_gate: 'blocked', mathematical_validation: 'not_claimed', ...extra};
}

test('decisions come only from structured current interpretation rows, ordered by severity', () => {
  const v = view();
  const low = interpretation('low', 'AmbiguityEntry', 'open', 'low');
  const high = interpretation('high', 'AmbiguityEntry', 'open', 'high');
  const medium = interpretation('medium', 'AssumptionEntry', 'proposed');
  const critical = interpretation('critical', 'AmbiguityEntry', 'open', 'critical');
  v.status.interpretations = [low, high, medium, critical];
  assert.deepEqual(ui.decisionItems(v), [critical, high, medium, low]);
  assert.equal(ui.decisionItems(v)[0], critical, 'existing fields and evidence are preserved, not invented');
});
test('conditional open ambiguity remains a discussion item while accepted is not mathematical validation', () => {
  const v = view();
  const conditional = interpretation('conditional', 'AmbiguityEntry', 'open', 'medium', {freeze_gate: 'conditional'});
  v.status.interpretations = [conditional,
    interpretation('accepted', 'AssumptionEntry', 'accepted', 'high', {mathematical_validation: 'pending'}),
    interpretation('checked', 'AssumptionEntry', 'accepted', 'high', {mathematical_validation: 'validated_checks'})];
  assert.deepEqual(ui.decisionItems(v), [conditional]);
  assert.equal(ui.decisionItems(v)[0].freeze_gate, 'conditional');
});
test('stale accepted or resolved interpretations need attention, but historical versions do not', () => {
  const v = view();
  const stale = interpretation('stale', 'AssumptionEntry', 'accepted', 'high', {current_errors: ['来源已变化']});
  v.objects.old = {kind: 'AmbiguityEntry', is_current: false};
  v.status.interpretations = [stale, interpretation('old', 'AmbiguityEntry', 'open', 'high', {is_current: false}),
    interpretation('resolved', 'AmbiguityEntry', 'resolved'), interpretation('other', 'ResultRecord', 'open')];
  assert.deepEqual(ui.decisionItems(v), [stale]);
  delete v.status.interpretations[1].is_current;
  assert.deepEqual(ui.decisionItems(v), [stale], 'an explicit historical object is excluded even without a row flag');
});
test('missing projection never falls back to old objects or keyword matching', () => {
  const v = view(); delete v.status.interpretations;
  v.status.blockers = ['等待人工确认'];
  v.objects.old = {kind: 'AmbiguityEntry', payload: {status: 'open'}};
  assert.deepEqual(ui.decisionItems(v), []);
});

function sharedInterpretations(){
  const v=view();
  v.status.interpretations=['Q1','Q2'].flatMap(question=>{
    const ambiguity=interpretation('ambiguity.'+question,'AmbiguityEntry','open','medium',{question,payload:{question,ambiguity_id:'AMB-'+question,source_anchor:'题目同一段',interpretations:['母线侧','电池侧'],severity:'medium',impact:'改变边界',status:'open',resolution:'',requirement_ids:['REQ-'+question]}});
    const assumption=interpretation('assumption.'+question,'AssumptionEntry','accepted','medium',{question,mathematical_validation:'pending',payload:{question,assumption_id:'ASM-'+question,statement:'暂以母线侧为准',status:'accepted',rationale:'可逆基线',linked_ambiguity_ids:['AMB-'+question],linked_requirement_ids:['REQ-'+question],review:{action:'accept',rationale:'等待检查',at:question}}});
    return [ambiguity,assumption];
  });
  for(const row of v.status.interpretations)v.objects[row.object_id]={id:row.object_id,kind:row.kind,is_current:true,status:'recorded',effective_status:'recorded',current_errors:[],payload:row.payload,files:[],dependencies:row.kind==='AssumptionEntry'?['ambiguity.'+row.question]:[]};
  return v;
}
test('only identical cross-question interpretations group while retaining exact member objects',()=>{
  const v=sharedInterpretations(),before=JSON.stringify(v);
  const groups=ui.interpretationGroups(v,ui.decisionItems(v));
  assert.equal(groups.length,1);assert.deepEqual(groups[0].questions,['Q1','Q2']);
  assert.equal(groups[0].items[0],v.status.interpretations[0]);assert.equal(groups[0].items[1],v.status.interpretations[2]);
  assert.equal(ui.decisionItems(v).length,2,'the per-question API remains ungrouped');
  assert.equal(JSON.stringify(v),before);
});
test('same title or statement never merges different semantics, states, severity, evidence or choices',()=>{
  for(const mutate of [r=>{r.payload.interpretations[0]='另一端口';},r=>{r.payload.status='resolved';},r=>{r.status='resolved';},r=>{r.payload.severity='high';},r=>{r.freeze_gate='conditional';},r=>{r.payload.resolution='电池侧';},r=>{r.payload.review={selected_interpretation:'电池侧'};},r=>{r.current_errors=['来源变化'];},r=>{r.payload.source_anchor='另一段';},r=>{r.payload.impact='不同影响';},r=>{r.payload.new_semantic_field='不同值';}]){
    const v=sharedInterpretations();mutate(v.status.interpretations[2]);
    assert.equal(ui.interpretationGroups(v,[v.status.interpretations[0],v.status.interpretations[2]]).length,2);
  }
  for(const mutate of [r=>{r.payload.statement='暂以电池侧为准';},r=>{r.payload.status='rejected';},r=>{r.mathematical_validation='validated_checks';},r=>{r.payload.review.rationale='不同理由';},r=>{r.payload.validation_plan='不同检查';}]){
    const v=sharedInterpretations();mutate(v.status.interpretations[3]);
    assert.equal(ui.interpretationGroups(v,[v.status.interpretations[1],v.status.interpretations[3]]).length,2);
    assert.equal(ui.interpretationGroups(v,ui.decisionItems(v)).length,2,'different related assumption choices also separate ambiguities');
  }
});
test('missing, historical, conflicting or same-question records cannot silently merge',()=>{
  for(const mutate of [v=>{delete v.objects['ambiguity.Q2'];},v=>{v.objects['ambiguity.Q2'].is_current=false;},v=>{v.status.interpretations[2].question='Q1';},v=>{v.status.interpretations[2].payload.interpretations=[];},v=>{v.objects['ambiguity.Q2'].dependencies=['unknown'];},v=>{v.objects['ambiguity.Q2'].payload={...v.objects['ambiguity.Q2'].payload,resolution:'不同对象详情'};},v=>{v.objects['ambiguity.Q2'].files=[{path:'不同来源.md'}];}]){
    const v=sharedInterpretations();mutate(v);
    assert.equal(ui.interpretationGroups(v,[v.status.interpretations[0],v.status.interpretations[2]]).length,2);
  }
});
test('structured assumption blockers retain every exact reason and never infer content from an id',()=>{
  const v=sharedInterpretations(),texts=['Q1 未完成','Q1 已接受假设仍待实际核验：ASM-Q1','Q2 已接受假设仍待实际核验：ASM-Q2','Q3 已接受假设仍待实际核验：ASM-MISSING'];
  const rows=ui.blockerItems(v,texts,true);assert.equal(rows.length,3);
  assert.equal(rows[1].items.length,2);assert.deepEqual(rows[1].originals,texts.slice(1,3));
  assert.equal(rows[1].items[0].payload.statement,'暂以母线侧为准');assert.equal(rows[2].items.length,0);
  assert.equal(ui.blockerItems(v,texts).length,4,'ordinary and per-question lists do not aggregate');
  v.status.interpretations[3].mathematical_validation='validated_checks';
  assert.equal(ui.blockerItems(v,texts,true).length,4,'different validation states retain separate blockers');
});
test('cursor stores no titles, payloads, result values, or old-version objects', () => {
  const v = view();
  v.objects.old = {...v.objects.result, id: 'old', is_current: false};
  const cursor = ui.makeVisit(v), raw = JSON.stringify(cursor);
  assert.equal(cursor.version, 1);
  assert.deepEqual(Object.keys(cursor.objects), ['result']);
  assert.deepEqual(Object.keys(cursor.objects.result).sort(), ['hash', 'status']);
  assert.doesNotMatch(raw, /私人|123456\.789|cost|payload|definition|title/);
  assert.deepEqual(ui.parseVisit(raw, v), cursor);
});
test('first visit has an explicit reset and unchanged observations have no changes', () => {
  const v = view();
  assert.deepEqual(ui.changeItems(v, null), {reset: true, items: [], otherChanges: false});
  assert.deepEqual(ui.changeItems(v, ui.makeVisit(v)), {reset: false, items: [], otherChanges: false});
});
test('malformed storage, unknown fields, spoofed status text, and forged payload text are rejected', () => {
  const v = view(), baseline = ui.makeVisit(v);
  for (const raw of [null, '', '{', 'null', '[]', '{}', '"text"']) assert.equal(ui.parseVisit(raw, v), null);
  for (const mutate of [x => {x.text = '已全部通过';}, x => {x.objects.result.payload = '伪造结果';},
    x => {x.objects.result.status = '已全部核验';}, x => {x.objects.result.hash = 'forged';},
    x => {x.objects = [];}, x => {x.version = 2;}, x => {x.state_hash = '<script>';},
    x => {x.checked_at = 'not a date';}, x => {x.checked_at = '2026-02-30T00:00:00Z';}, x => {x.revision = 1.5;}]) {
    const cursor = copy(baseline); mutate(cursor);
    assert.equal(ui.parseVisit(JSON.stringify(cursor), v), null);
  }
});
test('cross-project, future revision and future reading time are rejected', () => {
  const v = view(), cursor = ui.makeVisit(v);
  for (const patch of [{project_id: 'other-project'}, {revision: 4}, {revision: -1},
    {checked_at: '2027-01-01T00:00:00Z'}]) assert.equal(ui.parseVisit(JSON.stringify({...cursor, ...patch}), v), null);
});
test('same revision file drift is detected even when no item changed', () => {
  const v = view(), cursor = ui.makeVisit(v); v.file_observation_hash = sha('c');
  assert.deepEqual(ui.changeItems(v, cursor), {reset: false, items: [], otherChanges: true});
});
test('same revision stale result and task are linked using current records only', () => {
  const v = view(), cursor = ui.makeVisit(v);
  v.objects.result.current_errors = ['绑定文件已改变']; v.tasks.task.current_errors = {result: ['来源已改变']};
  const result = ui.changeItems(v, cursor);
  assert.deepEqual(result.items, [{kind: 'stale', object_id: 'result'}, {kind: 'stale', task_id: 'task'}]);
  assert.doesNotMatch(JSON.stringify(result), /verified|running|来源|绑定|hash|123456/);
});
test('a bound-file observation changes the result marker before relying on revision', () => {
  const v = view(); v.objects.result.files = [{path: 'results/output.csv'}];
  v.observed_files['results/output.csv'] = {sha256: sha('a')};
  const cursor = ui.makeVisit(v); v.observed_files['results/output.csv'].sha256 = sha('c');
  assert.deepEqual(ui.changeItems(v, cursor).items, [{kind: 'result', object_id: 'result'}]);
});
test('new current model, result, task and requirement changes are not truncated', () => {
  const v = view(), cursor = ui.makeVisit(v);
  v.objects.model = {kind: 'ModelSpec', is_current: true, status: 'frozen', payload: {method: 'LP'}};
  for (let i = 0; i < 20; i++) v.objects['result' + i] = {...v.objects.result, id: 'result' + i};
  v.tasks.task.status = 'completed'; v.status.requirements.rows[0].status = 'missing';
  const result = ui.changeItems(v, cursor);
  assert.equal(result.items.length, 23);
  assert(result.items.some(x => x.kind === 'model' && x.object_id === 'model'));
  assert(result.items.some(x => x.kind === 'task' && x.task_id === 'task'));
  assert(result.items.some(x => x.kind === 'requirement' && x.requirement_id === 'req'));
});
test('withdrawn, inactive and superseded records give a generic notice without old record details', () => {
  const v = view(), cursor = ui.makeVisit(v);
  v.objects.result.is_current = false;
  delete v.tasks.task;
  v.requirements.req.active = false;
  const result = ui.changeItems(v, cursor);
  assert.deepEqual(result, {reset: false, items: [], otherChanges: true});
});
test('journal-only or other authority change is not described as no change', () => {
  const v = view(), cursor = ui.makeVisit(v);
  v.revision++; v.state_hash = sha('c');
  assert.deepEqual(ui.changeItems(v, cursor), {reset: false, items: [], otherChanges: true});
});
test('old cursor status cannot supply current labels or verification', () => {
  const v = view(), cursor = ui.makeVisit(v);
  cursor.objects.result.status = 'verified';
  v.objects.result.status = 'failed';
  const result = ui.changeItems(v, cursor);
  assert.deepEqual(result.items, [{kind: 'result', object_id: 'result'}]);
  assert.doesNotMatch(JSON.stringify(result), /verified|failed|PASS/);
});
test('cursor comparison uses only current versions, independent of object map insertion order', () => {
  const v = view(), cursor = ui.makeVisit(v);
  const obj = v.objects.result;
  v.objects.result = {payload: obj.payload, files: obj.files, current_errors: obj.current_errors,
    status: obj.status, kind: obj.kind, id: obj.id, is_current: obj.is_current};
  v.objects.old = {...obj, is_current: false, payload: {private: 'changed history'}};
  assert.deepEqual(ui.changeItems(v, cursor), {reset: false, items: [], otherChanges: false});
});
test('all APIs leave authority and cursor untouched and never access storage or network', () => {
  const context = {window: {}};
  Object.defineProperty(context.window, 'localStorage', {get() {throw new Error('storage must be owned by the caller');}});
  context.fetch = () => {throw new Error('network must not be called');};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../dashboard/workbench.js'), 'utf8'), context);
  const v = view(), before = JSON.stringify(v), api = context.window.CopilotWorkbench;
  const cursor = api.makeVisit(v), cursorBefore = JSON.stringify(cursor);
  api.decisionItems(v); api.interpretationGroups(v, []); api.blockerItems(v, [], true); api.parseVisit(cursorBefore, v); api.changeItems(v, cursor);
  assert.equal(JSON.stringify(v), before); assert.equal(JSON.stringify(cursor), cursorBefore);
  assert.deepEqual(Object.keys(api).sort(), ['blockerItems', 'changeItems', 'decisionItems', 'interpretationGroups', 'makeVisit', 'parseVisit']);
});
test('missing observation metadata disables only the optional local cursor', () => {
  const v = view(); delete v.file_observation_hash;
  assert.equal(ui.makeVisit(v), null);
  assert.deepEqual(ui.changeItems(v, null), {reset: true, items: [], otherChanges: false});
});
test('prototype-like map keys and oversized persistence are rejected', () => {
  const v = view(), cursor = ui.makeVisit(v);
  const raw = JSON.stringify(cursor).replace('"result":', '"__proto__":');
  assert.equal(ui.parseVisit(raw, v), null);
  assert.equal(ui.parseVisit(' '.repeat(4000001), v), null);
  assert.equal({}.polluted, undefined);
});
