'use strict';
// Independent read-only help: no model mutations, AI starts, or feedback sends.
(() => {
  function createController({api,onChange=()=>{}}) {
    let generation=0;
    const state={open:false,loading:false,mode:'catalog',data:null,error:''};
    const notify=()=>onChange({...state});
    async function load(mode,topic){
      const token=++generation;Object.assign(state,{open:true,loading:true,mode,data:null,error:''});notify();
      try {
        const data=mode==='recap'?await api.recap():await api.tutorial(topic);
        if(token!==generation)return;
        if(!data||typeof data!=='object'||(mode==='catalog'&&!Array.isArray(data.features))||(mode==='lesson'&&!Array.isArray(data.sections))||(mode==='recap'&&typeof data.enabled!=='boolean'))throw new Error('返回的帮助内容不完整');
        state.data=data;
      }catch{if(token!==generation)return;state.error=mode==='recap'?'暂时无法读取本项目复盘，请稍后重试；未使用旧内容代替。':'暂时无法读取使用帮助，请稍后重试。仍可在当前 AI 对话中说“进入教学模式”。';}
      finally{if(token===generation){state.loading=false;notify();}}
    }
    return {state,catalog:()=>load('catalog'),lesson:topic=>load('lesson',topic),recap:()=>load('recap'),close(){generation++;Object.assign(state,{open:false,loading:false,data:null,error:''});notify();}};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={createController};return;}

  const $=id=>document.getElementById(id),dialog=$('help-dialog'),body=$('help-body'),message=$('help-status');
  if(!dialog||!body||!$('help-link'))return;
  const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);if(cls)node.className=cls;return node;};
  const button=(text,fn,cls='button')=>{const node=el('button',text,cls);node.type='button';node.addEventListener('click',fn);return node;};
  const paragraph=text=>el('p',text,'help-copy');
  const actions=(...buttons)=>{const node=el('div',undefined,'summary-actions');node.append(...buttons);return node;};
  function request(prompt){
    const box=el('details',undefined,'disclosure'),summary=el('summary','复制到当前 AI 对话');
    const field=el('textarea',undefined,'discussion-text');field.value=prompt;field.readOnly=true;field.setAttribute('aria-label','可复制的自然语言请求');
    const note=el('p','这里仅准备请求，不会启动 AI。复制后请粘贴并发送到当前对话。','muted small');
    box.append(summary,note,field,button('复制请求',async()=>{
      try{await navigator.clipboard.writeText(prompt);message.textContent='已复制请求。请粘贴并发送给当前 AI；页面没有启动 AI。';}
      catch{field.focus();field.select();message.textContent='未能自动复制。请求已选中，请手动复制并发送给当前 AI。';}
    }));return box;
  }
  function lessonCard(row){
    const card=el('section',undefined,'help-feature');card.append(el('h3',row.title),paragraph(row.purpose));
    const list=el('ol',undefined,'help-steps');for(const step of row.steps||[])list.append(el('li',step));card.append(list);
    card.append(el('p',row.limits,'muted small'),request(row.prompt));return card;
  }
  function render(state){
    if(!state.open){body.replaceChildren();message.textContent='';return;}
    body.replaceChildren();message.textContent='';
    if(!dialog.open)dialog.showModal();
    if(state.loading){message.textContent=state.mode==='recap'?'正在读取本项目已保存的复盘…':'正在读取使用帮助…';return;}
    if(state.error){body.append(paragraph(state.error),actions(button('重新读取',()=>state.mode==='recap'?controller.recap():controller.catalog()),button('返回功能目录',()=>controller.catalog())));return;}
    const data=state.data;
    if(state.mode==='catalog'){
      body.append(el('h2','先了解功能，再回到你的题目'),paragraph(data.introduction),paragraph('你可以只学一项，也可以完整了解。阅读和退出教学不会初始化项目、修改建模状态或提交反馈。'));
      body.append(actions(button('完整教学',()=>controller.lesson('all'),'button primary'),button('查看本项目复盘',()=>controller.recap())));
      const grid=el('div',undefined,'help-feature-grid');
      for(const row of data.features){const card=el('section',undefined,'help-feature');card.append(el('h3',row.title),paragraph(row.purpose),el('p','适合：'+row.when_to_use,'muted small'),el('p','入口：'+row.entry,'muted small'),el('p',row.status,'help-availability'),button('学习：'+row.title,()=>controller.lesson(row.topic),'object-link'));grid.append(card);}body.append(grid);
    }else if(state.mode==='lesson'){
      body.append(actions(button('返回功能目录',()=>controller.catalog()),button('查看本项目复盘',()=>controller.recap())));
      body.append(el('h2',data.title));for(const row of data.sections)body.append(lessonCard(row));
      body.append(el('h3','退出后怎样继续'),paragraph('关闭本窗口即可回到原来的页面。回到对话时，可以发送下面的请求，让 AI 核对最新状态后续接。'),request(data.exit_prompt));
    }else{
      body.append(actions(button('返回功能目录',()=>controller.catalog()),button('重新读取本项目复盘',()=>controller.recap())));
      body.append(el('h2','本次复盘'),paragraph(data.notice||'只读取本机当前项目已保存的复盘。'));
      if(data.enabled&&data.recap){
        const recap=data.recap;body.append(el('h3',recap.title||'已保存的复盘'));
        if(recap.observed_at){const date=new Date(recap.observed_at);body.append(el('p',Number.isNaN(date.valueOf())?'记录时间尚未明确':'记录时间：'+date.toLocaleString('zh-CN'),'muted small'));}
        if(recap.partial)body.append(el('p','过程记录不完整：以下只覆盖实际取得的材料。','help-limitation'));
        body.append(paragraph('这是历史过程说明。当前结果能否使用，请以重新检查的项目状态和文件为准。'));
        body.append(el('pre',recap.markdown||'这份复盘尚无正文。','recap-text'));
      }else body.append(paragraph(data.enabled?'当前没有可展示的本项目复盘。你可以先了解保存范围，再决定是否开启。':'个人记录暂不可读；项目建模和手动教学仍可继续。'));
      body.append(request('介绍本项目过程记录与本次复盘的范围，先给样例；我选择前不要新增对话留存。'));
    }
  }
  const controller=createController({api:window.CopilotData,onChange:render});
  const invitation=$('help-invitation'),inviteKey='mathmodel.help.invitation.v1';
  function dismiss(){if(invitation)invitation.hidden=true;try{window.localStorage.setItem(inviteKey,'dismissed');}catch{/* Help is usable without persistence. */}}
  $('help-link').addEventListener('click',()=>{dismiss();controller.catalog();});
  $('help-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{controller.close();$('help-link').focus();window.dispatchEvent(new Event('copilot-preview-change'));});
  let alreadyShown=false;try{alreadyShown=window.localStorage.getItem(inviteKey)==='dismissed';}catch{/* No stored preference; keep a skippable invitation. */}
  if(invitation&&!alreadyShown){invitation.hidden=false;invitation.append(el('strong','先花一点时间了解怎样配合'),paragraph('先理解题目、比较方法，再运行与检查。关键判断和论文定稿由你完成；使用帮助可以随时再打开。'),actions(button('进入教学模式',()=>{dismiss();controller.catalog();},'button primary'),button('直接开始',dismiss),button('本浏览器不再主动提示',dismiss,'button quiet')));}
})();
