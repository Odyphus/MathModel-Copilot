'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const ui=require('../dashboard/app.js');
test('ambiguous metric keys never imply traffic capacity or seconds',()=>{
  const rows=ui.metricRows({payload:{metrics:{capacity:12000,horizon:24}}});
  assert.deepEqual(rows,[['指标 1（含义未登记）','12000','单位未登记'],['指标 2（含义未登记）','24','单位未登记']]);
  assert.doesNotMatch(JSON.stringify(rows),/车辆|通行|秒/);
});
test('explicit display declarations preserve domain-specific units',()=>{
  const rows=ui.metricRows({metric_details:{items:[{label:'储能容量',unit:'kWh',value:12000,declaration_status:'declared'},{label:'预测跨度',unit:'h',value:24,declaration_status:'declared'}]}});
  assert.deepEqual(rows,[['储能容量','12000','kWh'],['预测跨度','24','h']]);
});
test('conflicting declarations are not silently resolved and unknown English is not guessed',()=>{
  assert.deepEqual(ui.metricRows({metric_details:{items:[{label:null,unit:null,value:3,declaration_status:'conflicting'},{label:'Battery capacity',unit:'kWh',value:0,declaration_status:'declared'}]}}),[['指标 1（声明有冲突）','3','单位未登记'],['指标 2（含义未登记）','0','kWh']]);
});
test('predeclared criterion and actual values remain distinct from a pass flag',()=>{
  const [row]=ui.validationRows({checks:[{check_id:'known',status:'fail',criterion:'误差不得超过 0.01',predeclared:true,actual:0.05,evidence:['result.json']}]});
  assert.equal(row.criterion,'误差不得超过 0.01');assert.equal(row.actual,0.05);assert.equal(row.predeclared,true);assert.equal(row.status,'fail');
  assert.equal(ui.validationRows({checks:[{check_id:'missing',status:'pass'}]})[0].predeclared,false);
});
test('historical verified records are still visibly old versions',()=>{assert.equal(ui.statusLabel('verified',{is_current:false}),'旧版本');assert.equal(ui.statusLabel('verified',{is_current:true}),'已检查');});
