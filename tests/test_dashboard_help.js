'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {createController}=require('../dashboard/help.js');
const catalog={version:1,read_only:true,features:[{topic:'models',title:'比较候选建模思路'}]};
const lesson={version:1,read_only:true,sections:[{topic:'models',title:'比较候选建模思路'}]};
function setup(){
  const requests=[],events=[];
  const api={tutorial:topic=>new Promise((resolve,reject)=>requests.push({type:'tutorial',topic,resolve,reject})),recap:()=>new Promise((resolve,reject)=>requests.push({type:'recap',resolve,reject}))};
  return {requests,events,controller:createController({api,onChange:state=>events.push(state)})};
}
test('catalog and single topic remain available after closing teaching',async()=>{
  const h=setup(),first=h.controller.catalog();h.requests[0].resolve(catalog);await first;assert.equal(h.controller.state.mode,'catalog');
  h.controller.close();assert.equal(h.controller.state.open,false);assert.equal(h.controller.state.data,null);
  const second=h.controller.lesson('models');assert.equal(h.requests[1].topic,'models');h.requests[1].resolve(lesson);await second;assert.equal(h.controller.state.mode,'lesson');
});
test('late tutorial response cannot replace a later recap or reopened lesson',async()=>{
  const h=setup(),first=h.controller.catalog(),second=h.controller.recap();h.requests[1].resolve({enabled:true,recap:null,notice:'尚未保存本项目复盘'});await second;
  h.requests[0].resolve(catalog);await first;assert.equal(h.controller.state.mode,'recap');assert.equal(h.controller.state.data.recap,null);
  const third=h.controller.lesson('all');h.controller.close();h.requests[2].resolve(lesson);await third;assert.equal(h.controller.state.open,false);assert.equal(h.controller.state.data,null);
});
test('recap failure clears earlier personal text and produces an honest unavailable message',async()=>{
  const h=setup(),first=h.controller.recap();h.requests[0].resolve({enabled:true,recap:{markdown:'历史复盘正文'}});await first;
  const second=h.controller.recap();assert.equal(h.controller.state.data,null);h.requests[1].reject(new Error('C:/private/secret'));await second;
  assert.match(h.controller.state.error,/未使用旧内容代替/);assert.doesNotMatch(h.controller.state.error,/private|secret/);assert.equal(h.controller.state.data,null);
});
test('missing recap and disabled personal access are normal read-only outcomes',async()=>{
  for(const data of [{enabled:true,recap:null,notice:'尚未保存本项目复盘'},{enabled:false,recap:null,notice:'记录暂不可读'}]){
    const h=setup(),pending=h.controller.recap();h.requests[0].resolve(data);await pending;assert.equal(h.controller.state.error,'');assert.deepEqual(h.controller.state.data,data);
  }
});
test('invalid responses never become a successful teaching or recap view',async()=>{
  for(const mode of ['catalog','lesson','recap']){const h=setup(),pending=mode==='lesson'?h.controller.lesson('all'):h.controller[mode]();h.requests[0].resolve({});await pending;assert(h.controller.state.error);assert.equal(h.controller.state.data,null);}
});
test('controller only uses read functions and does not start AI or business writes',async()=>{
  const calls=[];const h=createController({api:{tutorial:async topic=>{calls.push(topic??'catalog');return topic?lesson:catalog;},recap:async()=>{calls.push('recap');return {enabled:true,recap:null};},write(){throw new Error('must not write');},startAI(){throw new Error('must not start');}}});
  await h.catalog();await h.lesson('all');await h.recap();h.close();assert.deepEqual(calls,['catalog','all','recap']);
});
