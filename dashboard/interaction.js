'use strict';
(() => {
  // This module collects opinions and displays execution receipts. Core retains
  // ownership of model adoption, experiments, validation and submission readiness.
  const labels={recorded:'已记录',queued:'等待处理',running:'正在分析',cancelling:'正在停止',completed:'已回复',failed:'未成功',interrupted:'已中断',cancelled:'已撤回',stale:'项目已变化，需重新分析'};
  const statusLabel=status=>labels[status]||'尚未确认';
  const questionLabel=value=>/^Q\d+$/i.test(value||'')?`第${Number(value.slice(1))}问`:/\p{Script=Han}/u.test(String(value||''))?String(value):'项目整体';
  const maxLength=4000;
  function continuation(context,text,question) {
    return ['请使用 MathModel Copilot 继续当前项目。',context?.title?`项目：${context.title}`:'',`讨论范围：${questionLabel(question)}`,`建模意见：${String(text||'').trim()||'请先概括当前进展和下一步。'}`,'请先读取本机项目的最新权威状态及相关上下文，再回答；不要把页面记录或 AI 回复当作已采用、已运行或已核验的依据。','本次先做分析和建议，不修改模型、参数、结果或论文。'].filter(Boolean).join('\n\n');
  }
  function createApi(fetcher) {
    async function request(method,payload,token) {
      let response;
      try {
        response=await fetcher('/api/interaction',{method,credentials:'omit',cache:'no-store',headers:method==='GET'?{'X-Copilot-Read':'1'}:{'Content-Type':'application/json','X-Copilot-Write':token},...(payload?{body:JSON.stringify(payload)}:{}),signal:AbortSignal.timeout(20000)});
      } catch {const e=new Error(method==='GET'?'未能读取意见记录，请检查本地服务后重试。':'发送结果尚未确认。输入已保留；请先刷新记录核对，重试时会复用同一次请求。');e.uncertain=method==='POST';throw e;}
      let body;
      try {body=await response.json();} catch {const e=new Error('本地服务返回的内容无法识别，请刷新记录后核对。');e.uncertain=method==='POST';throw e;}
      if(!response.ok||body.ok!==true){const e=new Error(body.message||'本次操作未成功，请刷新记录后重试。');e.status=response.status;throw e;}
      return body.result;
    }
    return {read:()=>request('GET'),write:(payload,token)=>request('POST',payload,token)};
  }
  function createController({api,onChange=()=>{},onMutation=()=>{},storage=null,id=()=>crypto.randomUUID()}) {
    let generation=0,lastProject=null,attempt=null,readError=false;
    const state={context:null,data:null,ready:false,loading:false,pending:false,message:'',draft:{text:'',question:''}};
    const notify=()=>onChange(state);
    const key=project=>'mathmodel.opinion.draft.'+project;
    const save=()=>{if(!lastProject||!storage)return;try{storage.setItem(key(lastProject),JSON.stringify({draft:state.draft,attempt}));}catch{/* Disabled storage does not block an in-memory draft. */}};
    function restore(project){try{const saved=JSON.parse(storage?.getItem(key(project))||'null');if(saved&&typeof saved.draft?.text==='string'){state.draft={text:saved.draft.text.slice(0,maxLength),question:typeof saved.draft.question==='string'?saved.draft.question:''};attempt=saved.attempt||null;}else{state.draft={text:'',question:''};attempt=null;}}catch{state.draft={text:'',question:''};attempt=null;}}
    function suspend(){generation++;state.ready=false;state.data=null;state.loading=false;notify();}
    async function observe(context){
      if(context.project_id!==lastProject){save();lastProject=context.project_id;restore(lastProject);state.message='';state.pending=false;}
      state.context=context;return refresh();
    }
    async function refresh(){
      if(!state.context)return;
      const token=++generation,project=state.context.project_id;state.loading=true;state.ready=false;notify();
      try {const data=await api.read();if(token!==generation)return;
        if(!data||data.project_id!==project||!Number.isInteger(data.revision)||data.revision<state.context.revision||!Array.isArray(data.requests)||data.requests.some(row=>!row||typeof row!=='object'||typeof row.text!=='string'||typeof row.status!=='string')||typeof data.enabled!=='boolean'||(data.enabled&&(typeof data.token!=='string'||!data.token)))throw new Error('意见记录与当前项目不一致，请刷新项目后再试。');
        state.data=data;state.ready=true;if(readError)state.message='';readError=false;
      }catch(error){if(token!==generation)return;state.data=null;state.ready=false;state.message=error.message;readError=true;}
      finally{if(token===generation){state.loading=false;notify();}}
    }
    function draft(text,question=state.draft.question){state.draft={text:String(text).slice(0,maxLength),question:String(question||'')};save();notify();}
    async function send(action,request=null){
      if(state.pending)return false;
      if(!state.ready||!state.data?.enabled){state.message='当前不能保存意见，可复制续接说明到 AI 对话。';notify();return false;}
      if(action==='ask'&&state.data.assistant?.available!==true){state.message='尚未连接可用的 AI 执行入口，可先保存意见或复制续接说明。';notify();return false;}
      if(!['note','ask','cancel'].includes(action))return false;
      const text=state.draft.text.trim(),question=state.draft.question||null;
      if(action!=='cancel'&&!text){state.message='先写下你想讨论的问题或意见。';notify();return false;}
      if(action==='cancel'&&(!request||!['recorded','queued','running'].includes(request.status)))return false;
      const project=state.context.project_id;
      const signature=JSON.stringify([project,action,action==='cancel'?request.id:text,action==='cancel'?null:question]);
      // A lost HTTP response can have committed. Reuse the entire original body,
      // including its revision, so Store idempotency cannot create a second job.
      const previous=attempt?.payload;
      const retry=attempt?.signature===signature&&previous?.project_id===project&&previous.action===action&&Number.isInteger(previous.expected_revision)&&typeof previous.request_id==='string'&&/^[\w.-]{1,120}$/.test(previous.request_id)&&(action==='cancel'?previous.id===request.id:previous.text===text&&(previous.question||null)===question)&&Object.keys(previous).every(key=>['action','request_id','expected_revision','project_id','id','text','question'].includes(key));
      const payload=retry?previous:{action,request_id:id(),expected_revision:state.data.revision,project_id:project,...(action==='cancel'?{id:request.id}:{text,...(question?{question}:{})})};
      attempt={signature,payload};save();state.pending=true;state.message=action==='cancel'?'正在提交撤回请求…':'正在提交…';notify();
      try {
        const result=await api.write(payload,state.data.token);
        if(!Number.isInteger(result?.revision)||typeof result?.result?.id!=='string'){const e=new Error('没有读到明确回执，请刷新记录核对；输入已保留。');e.uncertain=true;throw e;}
        if(project!==state.context?.project_id)return false;
        attempt=null;
        if(action!=='cancel'&&state.draft.text.trim()===text&&state.draft.question===(question||''))state.draft={text:'',question:state.draft.question};
        save();state.message=action==='note'?'意见已记录。尚未发送给 AI。':action==='ask'?'分析请求已登记，处理进展见下方。':'撤回请求已登记，以下方实际状态为准。';
        state.pending=false;await refresh();onMutation();return true;
      }catch(error){
        if(project!==state.context?.project_id)return false;
        if(!error.uncertain){attempt=null;save();}
        state.message=error.status===409?'项目已有新变化，未自动重发。请查看最新进展，确认后再次提交。':error.message;
        readError=false;state.pending=false;await refresh();if(error.status===409)onMutation();return false;
      }finally{if(project===state.context?.project_id){state.pending=false;notify();}}
    }
    return {state,observe,suspend,refresh,draft,send};
  }
  const exportsForTests={statusLabel,questionLabel,continuation,createApi,createController,maxLength};
  if(typeof module!=='undefined'&&module.exports){module.exports=exportsForTests;return;}
  const host=document.getElementById('interaction'),openButton=document.getElementById('interaction-link');
  if(!host)return;
  const el=(tag,className='',text='')=>{const node=document.createElement(tag);node.className=className;node.textContent=text;return node;};
  const btn=(text,fn,className='button')=>{const node=el('button',className,text);node.type='button';node.addEventListener('click',fn);return node;};
  const details=el('details','interaction-details'),summary=el('summary','','建模意见与 AI 回复');summary.id='interaction-heading';
  const intro=el('p','muted interaction-intro','这里用于与 AI 讨论当前建模项目。意见可先保存在本机，也可以请 AI 分析。回复供你判断，不表示模型已采用或结果已核验。');
  const mode=el('p','muted small'),form=el('form','interaction-form'),scopeLabel=el('label','','这条意见与哪部分有关'),scope=el('select');scope.id='opinion-question';scopeLabel.htmlFor=scope.id;
  const textLabel=el('label','','你想讨论什么'),input=el('textarea');input.id='opinion-text';textLabel.htmlFor=input.id;input.rows=4;input.maxLength=maxLength;input.placeholder='例如：第二问采用混合整数线性规划，这些约束是否完整？还需要哪些验证？';
  const hint=el('p','muted small','草稿只保存在当前浏览器会话；保存意见后才能在项目中保留。');hint.id='opinion-hint';input.setAttribute('aria-describedby',hint.id);
  const counter=el('span','muted small'),actions=el('div','interaction-actions'),message=el('p','interaction-message');message.setAttribute('role','status');message.setAttribute('aria-live','polite');
  const history=el('div','interaction-history'),historyTitle=el('h3','','意见记录与回复'),list=el('div'),refreshButton=btn('刷新记录',()=>controller.refresh(),'button quiet');
  const copyPreview=el('div','interaction-copy-preview');copyPreview.hidden=true;
  let latest=null,renderedRequests='',questionKey='',timer=null;
  function readableError(raw,fallback){return /\p{Script=Han}/u.test(String(raw||''))?String(raw).replace(/\b[\da-f]{8}-[\da-f-]{27,}\b/gi,'相关记录').replace(/\b(?:RUN|REQ|CTX|TASK)-[\w@.-]+/g,'相关记录'):fallback;}
  async function copy(){
    const value=continuation(latest?.context,input.value,scope.value);
    try {await navigator.clipboard.writeText(value);message.textContent='续接说明已复制，请到 AI 对话粘贴发送。尚未自动发送。';copyPreview.hidden=true;}
    catch {copyPreview.replaceChildren(el('p','muted small','浏览器没有允许自动复制，请选中下方内容复制到 AI 对话。'));const area=el('textarea');area.value=value;area.readOnly=true;area.rows=8;area.setAttribute('aria-label','可手动复制的续接说明');copyPreview.append(area);copyPreview.hidden=false;area.focus();area.select();}
  }
  const note=btn('保存意见',()=>controller.send('note')),ask=btn('请 AI 分析',()=>controller.send('ask'),'button primary'),copyButton=btn('复制续接说明',copy,'button quiet');
  form.addEventListener('submit',event=>event.preventDefault());
  input.addEventListener('input',()=>controller.draft(input.value,scope.value));scope.addEventListener('change',()=>controller.draft(input.value,scope.value));
  actions.append(note,ask,copyButton,counter);form.append(scopeLabel,scope,textLabel,input,hint,actions,message,copyPreview);
  const historyHeading=el('div','panel-heading');historyHeading.append(historyTitle,refreshButton);history.append(historyHeading,list);details.append(summary,intro,mode,form,history);host.append(details);
  function render(state){
    latest=state;host.hidden=!state.context;openButton.hidden=!state.context;
    if(!state.context)return;
    const questions=state.context.questions||[],nextQuestionKey=JSON.stringify([state.context.project_id,questions]);
    if(questionKey!==nextQuestionKey){questionKey=nextQuestionKey;scope.replaceChildren();const all=el('option','','项目整体');all.value='';scope.append(all);questions.forEach(q=>{const option=el('option','',q.name||questionLabel(q.id));option.value=q.id;scope.append(option);});}
    if(input.value!==state.draft.text)input.value=state.draft.text;
    const validQuestion=questions.some(q=>q.id===state.draft.question)?state.draft.question:'';scope.value=validQuestion;
    if(state.draft.question!==validQuestion){controller.draft(state.draft.text,validQuestion);return;}
    counter.textContent=`${state.draft.text.length} / ${maxLength} 字`;
    const enabled=state.ready&&state.data?.enabled===true;
    note.hidden=ask.hidden=state.ready&&state.data?.enabled===false;
    note.disabled=!enabled||state.pending||!state.draft.text.trim();ask.disabled=note.disabled||state.data?.assistant?.available!==true;
    refreshButton.disabled=state.loading||state.pending;
    note.textContent=state.pending?'正在提交…':'保存意见';
    message.textContent=readableError(state.message,'操作未成功，请刷新记录后重试；草稿仍保留。');
    if(!state.message)message.textContent='';
    mode.textContent=state.loading?'正在读取本机意见记录…':!state.ready?'意见记录暂不可用，可以先保留草稿或复制续接说明。':!state.data.enabled?'当前是只读工作台。复制续接说明到 AI 对话后，助手才会收到。':state.data.assistant?.available?'已配置本地 AI 执行入口，登录、额度和权限会在提交时检查。只有点击“请 AI 分析”才会发起模型请求；刷新记录不会调用模型。':readableError(state.data.assistant?.reason,'尚未连接可用的 AI 执行入口，可以先保存意见，或复制续接说明到现有 AI 对话。');
    const workspaceMode=document.getElementById('workspace-mode');if(workspaceMode)workspaceMode.textContent=enabled?'本地 · 可记录意见':'本地 · 只读工作台';
    const requests=state.ready?state.data.requests:[],requestKey=JSON.stringify([requests,state.pending,state.ready]);
    if(renderedRequests!==requestKey){renderedRequests=requestKey;list.replaceChildren();
      if(!state.ready)list.append(el('p','muted small','尚未读取到当前记录，未显示上一次的处理状态。'));
      else if(!requests.length)list.append(el('p','muted small','还没有保存的意见。可以先记下疑问，稍后再继续。'));
      else requests.slice().reverse().forEach((request,index)=>{
        const item=el('article','opinion-item'),top=el('div','row-inline');
        const badge=el('span','badge',statusLabel(request.status));if(['failed','interrupted','stale'].includes(request.status))badge.className+=' warning';
        top.append(el('strong','',questionLabel(request.question)),badge);
        const date=new Date(request.updated_at||request.created_at);if(!Number.isNaN(date.valueOf()))top.append(el('time','muted small',date.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})));
        item.append(top,el('p','opinion-text',String(request.text||'')));
        if(request.reply){const reply=el('details','opinion-reply');reply.open=index<3;reply.append(el('summary','','查看 AI 回复（供参考）'),el('div','opinion-reply-text',String(request.reply)));item.append(reply);}
        if(request.status==='completed')item.append(el('p','muted small','已收到分析回复；采用、计算和核验仍需按项目流程进行。'));
        if(request.error)item.append(el('p','opinion-error',readableError(request.error,'本次分析未成功。可复制续接说明到现有 AI 对话继续。')));
        if(request.status==='recorded')item.append(el('p','muted small','仅保存了意见，尚未发送给 AI。'));
        if(request.status==='stale')item.append(el('p','muted small','分析期间项目有变化，请依据最新进展重新提问。'));
        if(request.status==='cancelling')item.append(el('p','muted small','已请求停止，正在等待执行器确认。此时不能视为已经停止。'));
        if(enabled&&['recorded','queued','running'].includes(request.status)){const cancel=btn(request.status==='running'?'停止分析':'撤回',()=>controller.send('cancel',request),'button quiet');cancel.disabled=state.pending;item.append(cancel);}
        list.append(item);
      });
    }
    clearTimeout(timer);
    if(state.ready&&!state.pending&&document.visibilityState!=='hidden')timer=setTimeout(()=>controller.refresh(),requests.some(r=>['queued','running','cancelling'].includes(r.status))?3000:15000);
  }
  let storage=null;try{storage=window.sessionStorage;}catch{/* Private browsing can disable storage. */}
  const controller=createController({api:createApi(window.fetch.bind(window)),storage,onChange:render,onMutation:()=>window.dispatchEvent(new Event('copilot-interaction-updated'))});
  openButton.addEventListener('click',()=>{details.open=true;host.scrollIntoView({block:'start'});input.focus({preventScroll:true});});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')clearTimeout(timer);});
  window.CopilotInteraction={observe:context=>controller.observe(context),suspend:()=>{clearTimeout(timer);controller.suspend();}};
})();
