'use strict';
(() => {
  const workbench=typeof module!=='undefined'&&module.exports?require('./workbench.js'):window.CopilotWorkbench;
  // Presentation only: no writes, no new business facts, no translated source storage.
  const states={verified:'已检查',executed:'已运行，待检查',generated:'已生成，待检查',stale:'需要重新检查',failed:'未成功',timeout:'运行超时',interrupted:'运行已中断',missing_outputs:'缺少结果文件',pending:'待开始',running:'进行中',completed:'已完成',blocked:'暂时无法继续',unknown:'尚未确认',missing:'尚未提供',not_applicable:'本项不适用',not_executed:'尚未执行',received:'已收到更新',adopted:'已采用',frozen:'已锁定版本',awaiting_submission:'待提交',submitted:'已提交',receipt_received:'已收到提交回执',checked:'已完成材料检查',NOT_READY:'尚不能提交',pass:'检查通过',draft:'草稿',not_enabled:'未启用'};
  const kinds={ModelSpec:'模型方案',ParameterSet:'参数设置',ProblemContract:'题意与交付要求',DataContract:'数据说明',CodeManifest:'计算代码',ValidationPlan:'检查方案',RunRecord:'计算记录',ValidationReport:'检查报告',ResultRecord:'计算结果',EvidenceMapEntry:'论文结论',PaperSection:'论文章节',ArtifactRecord:'附件',DeliveryAudit:'提交材料检查',DeliveryPackage:'提交材料包',SubmissionAudit:'提交材料检查',SubmissionPackage:'提交材料包',Task:'任务',Requirement:'题目要求',RulesLock:'比赛规则',ReferenceRegistry:'参考文献'};
  const roles={modeler:'建模员',coder:'编程员',writer:'写作员',qa:'检查员',integrator:'协调人',human:'人工',agent:'智能助手',agent_evaluator:'助手检查'};
  Object.assign(kinds,{AmbiguityEntry:'题意解释',AssumptionEntry:'建模假设',AssumptionValidation:'假设核验'});
  const messages={
    'Historical/research checks are not formal submission readiness':'目前完成的是练习或研究检查，还不能据此确认可以正式提交。',
    'Formal visual review requires a human reviewer':'正式提交前，还需要人工检查论文排版。',
    'Package has not entered awaiting_submission':'提交材料还未进入待提交阶段。',
    'No current passing delivery audit':'当前论文和提交材料还没有通过完整检查。',
    'No current verified delivery package':'还没有检查通过的提交材料包。',
    'No current freeze bound to this audit':'检查完成后的材料版本尚未锁定，需要重新确认。',
    'Submission state has no current version-bound event evidence':'缺少与当前材料对应的提交或回执记录。',
    'Delivery audit basis changed; audit the current project again':'检查之后项目又有变化，请重新检查当前论文和提交材料。',
    'Requirement Matrix is incomplete':'题目要求还没有全部完成并核对。',
    'Requirement Matrix 尚未建立':'还没有列出每一问需要完成的内容。',
    'Copilot authority has not been initialized':'项目还没有初始化。',
    'References need a checked registry or a version-bound not-applicable review':'参考文献还需要核对，或说明本次不适用的原因。',
    'Citation checker requires the editable DOCX master':'检查引用还需要可编辑的论文原稿。',
    'No actual Word/TeX render receipt bound to the final paper':'缺少当前论文实际生成最终文档的记录。',
    'Render receipt does not establish a completed render':'现有记录还不能确认最终文档已生成完成。',
    'Render receipt is not bound to the current source/PDF':'论文原稿与最终文档的版本不一致，需要重新生成。',
    'Render execution log is missing':'缺少论文文档生成过程的记录。',
    'Render execution log hash changed':'论文文档生成过程的记录发生变化，需要重新检查。',
    'DOCX rendering needs the actual PDF metadata and visual QA evidence':'论文最终文档还需要文件检查和排版检查记录。',
    'Actual DOCX-derived PDF has not passed the migrated PDF audit':'论文生成的最终文档尚未通过检查。',
    'event simulation with finite policy/configuration enumeration':'通过事件模拟，比较有限的调度策略与机器配置。',
    'reproduce the existing tested implementation without claiming a new optimal solver':'复用已经测试的实现进行复算；本方案不作全局最优性声明。',
    'Restricted dispatch algorithms pass deterministic, fault and negative kernel cases; not global optimality':'限定的调度算法通过了确定性、故障和反例检查；这不代表已经证明全局最优。',
    'RGV executes one non-overlapping command':'搬运小车同一时刻只能执行一条指令。',
    'fixed machine tools and ordered two-phase transfer':'各机床的刀具固定，双工序按规定顺序转运。',
    'return to position zero by 28800 seconds':'在 28,800 秒内返回起始位置。',
    'Package manifest changed':'提交材料清单已改变，需要重新检查。',
    '执行当前文件的论文与交付审计':'检查论文和提交材料',
    '尚未执行交付审计':'论文和提交材料还没有完成检查。',
    '缺少版本绑定审计':'当前版本缺少论文和提交材料的检查记录。',
    'Limited dispatch policies and fixed-tool assignments; no global optimality proof':'只比较了有限的调度策略和固定工序分配，不能据此证明全局最优。',
    'Fault probability interpreted per machining start, with assumed uniform failure and repair timing':'故障概率按每次加工开始计算；故障发生和修复时间采用了均匀分布假设。',
    'At most one intermediate part; immediate clean/delivery; full service time charged for unload-only':'模型最多保留一个中间工件，清洗后立即交付；仅卸料时仍按完整服务时间计算。',
    'Fixed healthy-selected configuration in fault sensitivity, not scenario-wise reoptimization':'故障分析沿用正常情况下选出的配置，没有对每个故障情景重新优化。',
    'Monte Carlo mean intervals describe simulation sampling error, not factory generalization':'模拟结果的区间只反映抽样误差，不能直接推广到真实工厂。',
    'Historical benchmark; no human final review, current rules lock, formal submission or receipt':'这是历史题目复算记录，不能代替人工终审、当届规则确认、实际提交或提交回执。'
  };
  const ruleNames={language:'论文语言',minimum_font_size_pt:'最小字号',first_page:'首页要求',page_header:'页眉要求',page_limit:'页数限制',anonymity:'匿名要求',ai_disclosure:'人工智能工具使用说明'};
  const outputNames={single_algorithm:'单工序调度算法',two_algorithm:'双工序调度算法',fault_algorithm:'故障与维修算法',algorithm_cases:'算法检查',technical_summary:'技术说明',conservation:'流量守恒检查',capacity_and_policy:'通行能力与策略检查',selection_and_sensitivity:'方案选择与敏感性检查'};
  const hasChinese=s=>/[\u3400-\u9fff]/u.test(String(s||''));
  // Long digits (including decimal tails and scientific notation) are data,
  // not bare hashes. Numeric hashes require an explicit identifier/hash context.
  const opaque=/\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b|\b(?:RUN|CHECK)-[0-9a-fA-F]{12,}(?:@\d+)?\b|\b(?:REQ|REQOBJ|OBJ|CLAIM|PAPER|PARAM|PSET|MSOBJ)-[A-Za-z0-9_.-]+(?:@\d+)?\b|\bT-(?:Q\d+[A-Za-z0-9_.-]*|[0-9a-fA-F]{12,})(?:@\d+)?\b|\b[A-Za-z_][\w.-]*@\d+\b|(?:\b(?:[Hh][Aa][Ss][Hh]|[Ss][Hh][Aa](?:-?256)?|[Mm][Dd]5|[A-Za-z_]+_hash)|哈希)\s*(?:[:：=]|为)?\s*[0-9a-fA-F]{12,}\b|(?<!\d\.)\b(?!\d+(?:[eEdD][+-]?\d+)?[ABCDF]?\b)[0-9a-fA-F]{12,}\b|\b(?:model|params|problem|data|code|plan|result|paper)\.[A-Za-z0-9_.-]+(?:@\d+)?/g;
  const questionLabel=value=>/^Q\d+$/i.test(String(value))?`第${Number(String(value).slice(1))}问`:hasChinese(value)?String(value):'';
  const statusLabel=(state,object={})=>object.is_current===false?'旧版本':states[state]||'尚未确认';
  function plainText(value,fallback='这项内容尚未提供中文说明，请查看原文。'){
    const text=String(value??'').trim();if(!text)return '';if(messages[text])return messages[text];
    const manual=text.match(/^No automatic evaluator or bound human rule review for:\s*(.+)$/);
    if(manual)return `以下要求还需要确认：${manual[1].split(',').map(s=>ruleNames[s.trim()]||'其他比赛要求').join('、')}。`;
    if(/对象不是当前版本/.test(text))return '已有更新版本，这份记录只供回看。';
    if(/文件.*(变化|变更)|[Ff]ile.*(changed|drift)|哈希.*不|hash mismatch/.test(text))return '相关文件已被修改，需要重新检查后再使用。';
    if(/文件.*(缺失|不存在)|[Mm]issing file|[Ff]ile not found/.test(text))return '缺少相关文件，请补齐后重新检查。';
    if(/待重检|上游.*(变化|变更|过期)|依赖.*(变化|过期)/.test(text))return '依赖的内容有变化，需要重新检查相关结果。';
    if(/^Q\d+ 未完成$/.test(text))return text.replace(/Q\d+/,m=>questionLabel(m));
    if(/^Execute and independently validate Q\d+$/.test(text))return '计算并独立检查'+questionLabel(text.match(/Q\d+/)[0]);
    if(!hasChinese(text))return fallback;
    return text.replace(opaque,'相关记录')
      .replace(/\b(?:AMB|ASM)-(?:[A-Za-z0-9_.-]+|第\d+问-[A-Za-z0-9_.-]+)(?:@\d+)?/g,'相关解释记录')
      .replace(/\bQ\d+\b/g,questionLabel)
      .replace(/Requirement Matrix/g,'题目要求清单').replace(/EvidenceMap/g,'结论依据').replace(/Task Context/g,'任务交接说明')
      .replace(/\bCore\b/g,'项目记录').replace(/\bCLI\b/g,'项目工具').replace(/\bStage\s*\d+/g,'当前环节')
      .replace(/awaiting_submission/g,'待提交').replace(/historical_benchmark/g,'历史题目练习')
      .replace(/\b(?:stale|failed|timeout|interrupted|missing_outputs|verified|generated|executed)\b/g,m=>states[m])
      .replace(/\b(?:ModelSpec|ParameterSet|ProblemContract|DataContract|CodeManifest|ValidationPlan|RunRecord|ValidationReport|ResultRecord|EvidenceMapEntry|PaperSection|ArtifactRecord|DeliveryAudit|DeliveryPackage)\b/g,m=>kinds[m]);
  }
  function questionOf(object,records={},seen=new Set()){
    if(!object||seen.has(object))return '';seen.add(object);const p=object.payload||object;
    const direct=questionLabel(p.question||p.definition?.question||object.question);if(direct)return direct;
    const match=String(object.id||object.object_id||object.key||'').match(/(?:^|[.-])(Q\d+)(?=[.@-]|$)/);if(match)return questionLabel(match[1]);
    const values=new Set((object.dependencies||[]).map(id=>questionOf(records[id],records,new Set(seen))).filter(Boolean));return values.size===1?[...values][0]:'';
  }
  function displayTitle(object,records={}){
    const p=object.payload||object,q=questionOf(object,records),kind=kinds[object.kind]||'项目记录';
    if(object.kind==='AmbiguityEntry')return `${q?q+' · ':''}题意解释`;
    if(object.kind==='AssumptionEntry')return `${q?q+' · ':''}建模假设`;
    const title=p.definition?.requested_action||p.claim||p.title||object.title;
    if(object.kind==='EvidenceMapEntry'&&typeof title==='string'&&(title.length>120||/[\r\n]/.test(title)))return `${q?q+' · ':''}论文结论（展开查看完整内容）`;
    if(title&&hasChinese(title))return plainText(title);
    if(/^Execute and independently validate Q\d+$/.test(String(title)))return plainText(title);
    if(title==='Retained causal discrete-event heuristic')return `${q?q+' · ':''}因果离散事件调度模型`;
    if(object.kind==='ArtifactRecord') {
      const names={figure:'图表',table:'数据表',supporting_file_set:'配套材料',reference_registry:'参考文献资料'};
      const name=p.path?fileLabel(p.path):names[p.artifact_type]||kind;
      return `${q?q+' · ':''}${name}`;
    }
    if(object.kind==='PaperSection'&&p.path)return `${q?q+' · ':''}${fileLabel(p.path)}`;
    return q?q+'的'+kind:kind;
  }
  function projectName(identity={}){
    if(hasChinese(identity.title))return plainText(identity.title);
    const names={cumcm:'全国大学生数学建模竞赛',mcm:'美国大学生数学建模竞赛',icm:'美国大学生数学建模竞赛',diangong:'电工杯数学建模竞赛',generic:'数学建模项目'};
    const p=identity.problem||{},year=p.problem_year||p.year;return `${year?year+'年 · ':''}${names[identity.competition]||'数学建模项目'}${p.letter?' · '+p.letter+'题':''}`;
  }
  const idOf = o => o.object_id || o.id;
  const stateOf = o => o.effective_status || o.status || 'unknown';
  const errorsOf = o => Array.isArray(o.current_errors) ? o.current_errors : Object.values(o.current_errors || {}).flat();
  const currentObjects = v => Object.values(v.objects || {}).filter(o => o.is_current !== false);
  const isUsable = o => o.is_current !== false && stateOf(o) === 'verified' && !errorsOf(o).length;
  const modeLabel = mode => ({formal_contest:'正式比赛',historical_benchmark:'历史题目练习',open_research:'研究项目'})[mode] || '使用模式未确认';
  function requirementContext(definition={}) {
    const anchor=String(definition.source_anchor||'');
    const match=anchor.match(/^Problem B Task two, Table 1 parameter group (\d+); situation (single|two|fault)$/);
    if(match)return `第${Number(match[1])}组参数 · ${{single:'单工序',two:'双工序',fault:'故障情景'}[match[2]]}`;
    return hasChinese(anchor)?plainText(anchor):'';
  }
  function outputLabel(value,index=0) {
    if(outputNames[value])return outputNames[value];
    const match=String(value).match(/^group(\d+)_(single_schedule|two_schedule|fault_single|fault_two)$/);
    if(match)return `第${Number(match[1])}组${{single_schedule:'单工序调度结果',two_schedule:'双工序调度结果',fault_single:'故障情景单工序结果',fault_two:'故障情景双工序结果'}[match[2]]}`;
    return ({efficiency_comparison:'运行效率对比',official_result_tables:'填写并核对后的官方结果表'})[value]||plainText(value,`第${index+1}项结果或材料`);
  }
  function questionGroups(v) {
    const rows = v.status.requirements.rows || [], records = v.objects || {};
    const names = new Set([...Object.keys(v.status.requirements.questions || {}).map(questionLabel), ...rows.map(r => questionLabel(r.question)), ...currentObjects(v).map(o => questionOf(o, records))].filter(Boolean));
    return [...names].sort((a,b) => a.localeCompare(b,'zh-CN',{numeric:true})).map(name => {
      const requirements = rows.filter(r => questionLabel(r.question) === name);
      const objects = currentObjects(v).filter(o => questionOf(o, records) === name);
      const tasks = Object.values(v.tasks || {}).filter(t => (t.requirements || []).some(id => requirements.some(r => r.id === id)) || questionOf(t, records) === name);
      return {name, requirements, objects, tasks, model:objects.find(o => o.kind === 'ModelSpec'), results:objects.filter(o => o.kind === 'ResultRecord'), sections:objects.filter(o => o.kind === 'PaperSection')};
    });
  }
  function questionProgress(group) {
    const rows = group.requirements;
    if (rows.length && rows.every(r => r.status === 'verified' && r.contract_current !== false)) return {label:'本问要求已核对',tone:'good'};
    if (rows.some(r => r.status === 'stale' || r.contract_current === false) || group.objects.some(o => stateOf(o) === 'stale') || group.tasks.some(t => stateOf(t) === 'stale')) return {label:'部分内容需要重检',tone:'warning'};
    if (group.tasks.some(t => stateOf(t) === 'blocked')) return {label:'有事项需要先处理',tone:'warning'};
    if (group.objects.some(o => ['failed','timeout','interrupted','missing_outputs'].includes(stateOf(o)))) return {label:'有计算或检查未成功',tone:'danger'};
    if (group.results.length || group.objects.some(o => o.kind === 'RunRecord')) return {label:'已有计算记录，继续检查',tone:''};
    if (group.model) return {label:'已登记模型方案',tone:''};
    return {label:rows.length ? '已列出题目要求' : '进度尚未完整记录',tone:''};
  }
  function pendingConfirmations(v) {
    // Only actual recorded needs; never infer a decision, reviewer or approval.
    const all = [...(v.status.blockers || []), ...(v.status.submission.blockers || [])];
    return [...new Set(all.filter(text => /requires a human|human rule review|人工|待确认|需要确认|等待确认/i.test(text)))];
  }
  function currentProblems(v) {
    return currentObjects(v).filter(o => ['stale','failed','timeout','interrupted','missing_outputs'].includes(stateOf(o)) || errorsOf(o).length);
  }
  function modelSummary(model) {
    if (!model) return '';
    return displayTitle(model).replace(/^第\d+问\s*[·的]\s*/, '');
  }
  function nextAction(v) {
    const decisions=workbench.decisionItems(v);
    if(decisions.length){const group=workbench.interpretationGroups(v,decisions)[0],item=group.items[0];return `${group.questions.map(questionLabel).filter(Boolean).join('、')||'当前项目'}：${item.current_errors?.length?'先重新核对题意或假设的依据':item.kind==='AmbiguityEntry'?'比较题意的不同解释，再确定采用口径':'判断是否采用这项建模假设'}。`;}
    const confirmations = pendingConfirmations(v);
    if (confirmations.length) return plainText(confirmations[0], '有一项工作需要你确认，请查看下面的说明。');
    const task = v.status.current_task && (v.tasks[v.status.current_task.id] || v.status.current_task);
    if (task && stateOf(task) !== 'completed') return displayTitle({...task,kind:'Task'},v.objects);
    if (currentProblems(v).length) return '先检查发生变化或没有成功的内容，再继续使用相关结果。';
    // A completed audit must not become an instruction to repeat the same audit.
    const submission = v.status.submission;
    if (isUsable(v.objects?.[submission.audit_id] || {}) && /审计|audit/i.test(v.status.next_action || '')) {
      return submission.ready ? '查看已准备好的论文和材料，按比赛要求完成实际提交。' : '论文材料已有检查记录，请继续确认剩余的提交条件。';
    }
    return plainText(v.status.next_action || '', '先查看各问进展，再确定下一项工作。');
  }
  function parameterRows(payload={}) {
    // entries is the domain contract; parameters is retained for older records only.
    // An explicitly empty current list must never resurrect the legacy values.
    const entries=Array.isArray(payload.entries)?payload.entries:Array.isArray(payload.parameters)?payload.parameters:[];
    const units={dimensionless:'无量纲',kWh:'千瓦时',kW:'千瓦',MW:'兆瓦',MWh:'兆瓦时',hour:'小时',hours:'小时',h:'小时',minute:'分钟',minutes:'分钟',min:'分钟',second:'秒',seconds:'秒',s:'秒',yuan:'元',CNY:'元','yuan/kWh':'元/千瓦时','CNY/kWh':'元/千瓦时'};
    return entries.map((entry,index)=>{
      const item=entry&&typeof entry==='object'?entry:{};
      const name=hasChinese(item.meaning)?plainText(item.meaning):`参数 ${index+1}（含义待补充，原文见诊断记录）`;
      const value=item.current_value;
      const display=value===null||value===undefined?'尚未设置':typeof value==='boolean'?(value?'是':'否'):typeof value==='number'?(Number.isFinite(value)?String(value):'无效数值，需检查'):typeof value==='string'?(value.trim()?value.replace(opaque,'内部标识（见诊断记录）'):'尚未设置'):'复合取值（见诊断记录）';
      const unit=typeof item.unit==='string'&&item.unit.trim()?units[item.unit]||item.unit.replace(opaque,'内部标识（见诊断记录）'):'单位未记录';
      return [name,display,unit];
    });
  }
  function interactionContext(v) {
    const questions=[...new Set((v.status.requirements.rows||[]).map(row=>row.question).filter(value=>typeof value==='string'&&value))];
    return {project_id:v.project_id,revision:v.revision,title:projectName(v.identity),questions:questions.map(id=>({id,name:questionLabel(id)||'相关小问'}))};
  }
  function metricRows(object) {
    const details=object.metric_details?.items;
    const items=Array.isArray(details)?details:Object.entries(object.payload?.metrics||{}).filter(([,v])=>typeof v==='number'&&Number.isFinite(v)).map(([,value])=>({value}));
    return items.map((item,index)=>[item.declaration_status==='conflicting'?`指标 ${index+1}（声明有冲突）`:plainText(item.label,`指标 ${index+1}（含义未登记）`)||`指标 ${index+1}（含义未登记）`,String(item.value),typeof item.unit==='string'&&item.unit.trim()?item.unit.replace(opaque,'相关记录'):'单位未登记']);
  }
  function validationRows(payload) {
    return (Array.isArray(payload.checks)?payload.checks:[]).map((check,index)=>({name:outputNames[check.check_id]||`第${index+1}项检查`,status:check.status,criterion:typeof check.criterion==='string'?check.criterion:'',predeclared:check.predeclared===true,actual:check.actual,evidence:Array.isArray(check.evidence)?check.evidence:[]}));
  }
  function recheckGuide(object,v) {
    if(object.is_current===false||(!errorsOf(object).length&&stateOf(object)!=='stale'))return null;
    const records=v.objects||{},seen=new Set(),pending=[object],causes=[],unique=new Set();
    const add=cause=>{const key=JSON.stringify(cause);if(!unique.has(key)){unique.add(key);causes.push(cause);}};
    while(pending.length){const item=pending.pop(),id=idOf(item);if(seen.has(id))continue;seen.add(id);
      if(item.is_current===false){const latest=Object.values(records).find(o=>o.key===item.key&&o.is_current===true);if(latest)add({type:'version',id,latest:idOf(latest),message:`${kinds[item.kind]||'依据'}已有新版本，本条记录仍引用旧版本。`});}
      for(const file of item.files||[]){const observed=v.observed_files?.[file.path];if(observed?.unavailable)add({type:'file',id,message:`${kinds[item.kind]||'依据'}的关联文件当前无法读取。`});else if(observed?.sha256&&file.sha256&&observed.sha256.toLowerCase()!==file.sha256.toLowerCase())add({type:'file',id,message:`${kinds[item.kind]||'依据'}的关联文件与登记时不同。`});}
      for(const dep of item.dependencies||[])if(records[dep])pending.push(records[dep]);
    }
    const downstream=[],reached=new Set([idOf(object)]),queue=[idOf(object)],consumers=new Map();
    for(const item of Object.values(records))for(const dep of item.dependencies||[]){if(!consumers.has(dep))consumers.set(dep,[]);consumers.get(dep).push(item);}
    while(queue.length)for(const item of consumers.get(queue.shift())||[]){const id=idOf(item);if(reached.has(id))continue;reached.add(id);queue.push(id);if(item.is_current!==false)downstream.push(id);}
    return {causes,downstream,next:'先处理发生变化的依据，再重新运行受影响的计算和检查；论文结论与章节也需使用新的结果重新登记。'};
  }
  function metricHelpRequest(object) {
    const missing=(object.metric_details?.items||[]).filter(m=>m.declaration_status==='conflicting'||!m.label||!m.unit||!m.scope);
    if(!missing.length)return null;
    return `请检查这份结果的指标说明，先向我解释缺少哪些信息，按实际依据补充含义、单位和适用范围；不要从字段名猜测。\n结果记录：${idOf(object)}\n需核对的指标（最多列出 20 项）：\n${JSON.stringify(missing.slice(0,20).map(m=>({metric_path:m.metric_path,meaning:m.label,unit:m.unit,scope:m.scope,declaration_status:m.declaration_status,model_ids:m.metadata_source_ids})),null,2)}\n明确后更新相关 ModelSpec.outputs 的 meaning/unit/scope，使用 metric_path 对应指标。更新会影响后续记录，请先检查影响，再重跑、核验并更新受影响的论文；不要直接修改旧结果或工作台状态。`;
  }
  const exportsForTests = {recheckGuide,metricHelpRequest,metricRows,validationRows,interactionContext,parameterRows,changeDescription,requirementContext,outputLabel,statusLabel,plainText,questionLabel,questionOf,displayTitle,projectName,stateOf,isUsable,modeLabel,questionGroups,questionProgress,pendingConfirmations,currentProblems,nextAction};
  if (typeof module !== 'undefined' && module.exports) { module.exports = exportsForTests; return; }

  const $ = id => document.getElementById(id);
  const el = (tag,cls,text) => {const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
  const put = (parent,...children) => {children.filter(Boolean).forEach(c=>parent.append(c));return parent;};
  const icons = {overview:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',questions:'M8 6h12M8 12h12M8 18h12M3 6h1M3 12h1M3 18h1',results:'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',paper:'M5 3h10l4 4v14H5zM14 3v5h5M9 12h6M9 16h6',changes:'M5 4v16M5 7h9l4 4M5 17h9l4-4M3 4h4M3 20h4',check:'M4 12l5 5L20 6',cross:'M6 6l12 12M6 18L18 6',alert:'M12 3L2 21h20zM12 9v5M12 17v1',clock:'M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',info:'M12 11v6M12 7v1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',dash:'M6 12h12'};
  function icon(name) {const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',icons[name]||icons.info);svg.append(p);return svg;}
  const pages = [{id:'overview',name:'项目总览'},{id:'questions',name:'各问进展'},{id:'results',name:'成果与依据'},{id:'paper',name:'论文准备'}];
  const aliases = {tasks:'questions',runs:'results',evidence:'results'};
  let view=null,page='overview',renderedPage=null,loading=false,generation=0,detailStack=[],opener=null,fileGeneration=0,pollTimer=null;
  let visit=null,visitProject=null,visitPersistent=true;
  let readingStorage=null;try{readingStorage=window.localStorage;}catch{visitPersistent=false;}
  const visitKey=id=>'mathmodel.reading.v1:'+id;
  function rememberVisit(){
    visit=workbench.makeVisit(view);
    try{if(!readingStorage)throw new Error('no storage');readingStorage.setItem(visitKey(view.project_id),JSON.stringify(visit));}catch{visitPersistent=false;}
  }
  function observeVisit(next){
    if(visitProject!==next.project_id){visitProject=next.project_id;visit=null;try{visit=workbench.parseVisit(readingStorage?.getItem(visitKey(next.project_id)),next);}catch{visitPersistent=false;}}
    if(!visit||visit.revision>next.revision){view=next;rememberVisit();}
  }
  const filters={query:'',status:'all',scope:'current',category:'results'};
  const objects = () => Object.values(view?.objects || {});
  const titleOf = o => displayTitle(o,view?.objects || {});
  const byId = id => view?.objects?.[id];
  const stamp = (value,short=false) => {if(!value)return '时间未记录';const d=new Date(value);return Number.isNaN(d.valueOf())?'时间未记录':d.toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,...(!short?{year:'numeric'}:{})});};
  function button(text,fn,cls='button') {const b=el('button',cls,text);b.type='button';b.addEventListener('click',fn);return b;}
  function badge(state,object={}) {
    if(['AmbiguityEntry','AssumptionEntry'].includes(object.kind)&&object.is_current!==false&&!errorsOf(object).length&&state!=='stale')return tag(({open:'题意尚未确定',resolved:'题意口径已记录',proposed:'假设待判断',accepted:'假设已采用',rejected:'假设未采用'})[object.payload?.status]||'解释状态待确认');
    const good=['verified','completed','receipt_received','pass'].includes(state)&&object.is_current!==false,bad=['failed','timeout','interrupted','missing_outputs'].includes(state),warn=['stale','blocked','missing','NOT_READY'].includes(state)&&object.is_current!==false;
    return tag(statusLabel(state,object),good?'good':bad?'danger':warn?'warning':'');
  }
  function tag(label,tone='') {return put(el('span','badge '+tone),icon(tone==='good'?'check':tone==='danger'?'cross':tone==='warning'?'alert':'clock'),el('span','',label));}
  function notice(title,text,variant='') {return put(el('div','notice '+variant),icon(variant==='info'?'info':'alert'),put(el('div'),el('strong','',title),text?el('p','',text):null));}
  function empty(title,text) {return put(el('div','empty'),el('h2','',title),el('p','',text));}
  function heading(title,text) {return put(el('div','page-heading'),put(el('div'),el('h1','',title),text?el('p','subtitle',text):null));}
  function section(title,text) {return put(el('section','panel'),put(el('div','panel-heading'),el('h2','',title),text?el('span','muted',text):null));}
  function disclosure(label,...children) {return put(el('details','disclosure'),el('summary','',label),...children);}
  function originalText(text,label='查看原文说明') {return disclosure(label,el('p','muted small','以下是项目记录中的原文。'),el('pre','source-content',text));}
  function diagnostic(data) {
    // Technical identifiers remain in the downloadable diagnostic, off ordinary pages.
    return button('导出诊断记录',()=>{const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='项目诊断记录.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},'button quiet');
  }
  function explained(text,fallback='这项检查还需要处理，请查看原文了解具体原因。') {
    const translated=plainText(text,fallback),container=el('div','explained');container.append(el('span','',translated));
    if(translated===fallback)container.append(originalText(String(text),'查看具体原因（原文）'));
    return container;
  }
  function objectLink(o,label) {if(!o)return el('span','muted','记录尚未提供');const b=button(label||titleOf(o),e=>openDetail(o,e.currentTarget),'object-link');b.dataset.objectId=idOf(o)||'';if(o.kind==='Requirement'){const context=requirementContext(o.payload?.definition);if(context)b.append(el('span','link-context',context));}return b;}
  function resolve(id) {return byId(id)?objectLink(byId(id)):el('span','muted','关联内容未读取到，请刷新后再查看。');}
  function blockers(items,aggregate=false) {
    const ul=el('ul','block-list');
    workbench.blockerItems(view,items,aggregate).forEach(entry=>{
      const content=el('div');
      if(!entry.items.length){content.append(explained(entry.message));if(/\b(?:AMB|ASM)-/.test(entry.message))content.append(originalText(entry.message,'查看原始诊断'));}
      else {
        const questions=entry.items.map(item=>questionLabel(item.question)).filter(Boolean).join('、');
        content.append(el('p','',`${questions} · ${entry.message}`));
        const p=entry.items[0].payload;
        content.append(explained(p.statement||(p.interpretations||[]).join('；'),'内容已登记，请展开查看原文。'));
        content.append(disclosure('查看关联记录与诊断',...entry.items.map(item=>objectLink(byId(item.object_id),`${questionLabel(item.question)||'相关小问'} · 查看完整记录`)),el('pre','source-content',entry.originals.join('\n'))));
      }
      ul.append(put(el('li'),icon('alert'),content));
    });return ul;
  }
  function stateHint(o) {
    if(o.is_current===false)return '已有更新版本，这份记录保留供回看。';
    if(errorsOf(o).length)return plainText(errorsOf(o)[0],'这项内容还需要处理，请展开查看具体原因。');
    if(['AmbiguityEntry','AssumptionEntry'].includes(o.kind))return '这里只记录题意解释或假设选择；采用不等于已通过实际结果核验。';
    if(stateOf(o)==='verified')return ({RunRecord:'本次计算和配套检查已完成。',ResultRecord:'结果已与计算及检查记录核对。',PaperSection:'本节的结论来源已核对；整篇论文仍需单独检查。',EvidenceMapEntry:'本条结论的来源已核对；数字匹配不代表数学论证、因果关系或单位已获证明。',DeliveryAudit:'本次材料检查已通过；实际提交条件仍需分别确认。'})[o.kind]||'本项已通过已登记的检查。';
    return ({executed:'计算已完成，结果还需要检查。',generated:'内容已生成，尚未完成独立检查。',frozen:'已锁定所采用的版本，计算与结果检查仍需分别确认。',failed:'本次未成功，请查看具体原因。',timeout:'运行超时，需要检查计算设置。',interrupted:'运行途中停止，需要确认原因。',missing_outputs:'运行未提供要求的全部结果文件。',stale:'依据的内容有变化，需要重新检查。',pending:'这项工作尚未开始。',running:'最近的项目记录显示这项工作正在进行。',completed:'任务已记录完成，可查看对应产出。',blocked:'先处理前置问题，再继续这项工作。'})[stateOf(o)]||'当前情况尚未确认。';
  }
  function listRows(rows,headers) {const table=el('table'),head=el('tr');headers.forEach(h=>head.append(el('th','',h)));table.append(put(el('thead'),head));const body=el('tbody');rows.forEach(cells=>{const tr=el('tr');cells.forEach((c,i)=>{const td=el('td');td.dataset.label=headers[i];td.append(c instanceof Node?c:el('span','',c??'尚未提供'));tr.append(td);});body.append(tr);});table.append(body);return put(el('div','table-wrap'),table);}
  function objectTable(items) {return listRows(items.map(o=>[put(el('div'),objectLink(o),el('span','muted',kinds[o.kind]||'项目记录')),put(el('div'),badge(stateOf(o),o),el('span','muted',stateHint(o)))]),['内容','当前情况']);}
  function requirementObject(row) {const p=view.requirements[row.id]||{};return {id:row.id,kind:'Requirement',status:row.contract_current===false?'stale':row.status,payload:p,dependencies:[p.contract_id,...Object.values(p.coverage||{})].filter(Boolean),current_errors:row.contract_current===false?['题目要求的版本已变化']:[]};}
  function taskObject(t) {return {...t,kind:'Task',payload:t};}
  function questionPanel(group,expanded=false) {
    const progress=questionProgress(group),panel=section(group.name),top=panel.querySelector('.panel-heading');top.append(tag(progress.label,progress.tone));panel.classList.add('question-panel');
    const targets=[...new Set(group.requirements.map(r=>view.requirements[r.id]?.definition?.requested_action).filter(Boolean))];
    if(targets.length){const summary=targets.slice(0,expanded?targets.length:2).map(t=>plainText(t,'题目要求已记录，可展开查看原文。')).join('；');panel.append(el('p','question-target',summary+(targets.length>2&&!expanded?'等':'')));}
    if(group.model)panel.append(put(el('p','method-line'),el('span','muted','当前方案：'),objectLink(group.model,modelSummary(group.model)),stateOf(group.model)==='stale'?badge('stale'):null));
    const active=group.tasks.filter(t=>stateOf(t)!=='completed');
    if(active.length)panel.append(put(el('p','small-gap'),el('span','muted','当前工作：'),objectLink(taskObject(active[0]))));
    if(group.requirements.length)panel.append(el('p','muted small small-gap',`${group.requirements.length} 项题目要求，${group.requirements.filter(r=>r.status==='verified'&&r.contract_current!==false).length} 项已核对。`));
    const rows=group.requirements.map(r=>[objectLink(requirementObject(r)),badge(r.status)]);
    if(expanded){
      const decisions=workbench.decisionItems(view).filter(item=>questionLabel(item.question)===group.name);
      if(decisions.length)panel.append(disclosure('本问需要判断的事项',...decisions.map(decisionCard)));
      if(rows.length)panel.append(disclosure('逐项查看题目要求',listRows(rows,['需要完成什么','当前情况'])));
      if(group.tasks.length)panel.append(disclosure('任务安排与产出',objectTable(group.tasks.map(taskObject))));
      const bases=group.objects.filter(o=>['ModelSpec','ParameterSet','DataContract','ProblemContract','AmbiguityEntry','AssumptionEntry'].includes(o.kind));
      if(bases.length)panel.append(disclosure('方案、假设与数据',objectTable(bases)));
      if(group.results.length)panel.append(disclosure('本问结果',objectTable(group.results)));
    } else panel.append(button('查看本问详情',()=>{navigate('questions');document.querySelector(`[data-question="${group.name}"]`)?.scrollIntoView({block:'start'});},'object-link small-gap'));
    panel.dataset.question=group.name;return panel;
  }
  function usableFiles(items,predicate) {
    const map=new Map();items.forEach(o=>(o.files||[]).forEach(file=>{if(predicate(file.path)&&!map.has(file.path))map.set(file.path,{file,object:o});}));return [...map.values()];
  }
  function paperSummary() {
    const sections=currentObjects(view).filter(o=>o.kind==='PaperSection'),s=view.status.submission;
    const files=usableFiles(currentObjects(view).filter(o=>['PaperSection','DeliveryAudit','DeliveryPackage'].includes(o.kind)),p=>/\.(docx|pdf)$/i.test(p));
    if(!sections.length&&!files.length&&!s.audit_id&&!s.package_id)return null;
    const panel=section('论文准备');
    if(sections.length)panel.append(el('p','',`${sections.length} 个已登记章节中，${sections.filter(isUsable).length} 个的结论来源已核对。`));
    if(files.length)panel.append(el('p','muted small small-gap','已登记论文或相关文档，可查看文件及检查情况。'));
    panel.append(el('p','small-gap',s.ready?'当前已具备待提交条件，实际提交仍需单独完成。':modeLabel(view.identity.problem?.evaluation_mode)==='历史题目练习'?'当前为历史题目练习；正式提交条件尚未满足。':'正式提交条件尚未满足。'));
    panel.append(button('查看论文与材料',()=>navigate('paper'),'object-link small-gap'));return panel;
  }
  function decisionCard(item,members) {
    members=Array.isArray(members)?members:[item];
    const questions=members.map(member=>questionLabel(member.question)).filter(Boolean).join('、')||'当前项目';
    const p=item.payload||{},ambiguous=item.kind==='AmbiguityEntry',row=put(el('article','decision-item'),el('h3','',`${questions} · ${ambiguous?'这道题应该怎样理解':'是否采用这项假设'}`));
    row.dataset.decisionId=item.object_id;
    const severity={critical:'影响重大',high:'影响较大',medium:'影响中等',low:'影响较小'}[p.severity];
    if(item.current_errors?.length)row.append(notice('依据需要重新检查','请先核对相关文件，再继续判断。'));
    if(severity)row.append(el('p','muted small',severity));
    if(ambiguous){const options=el('ol','decision-options');(p.interpretations||[]).forEach(option=>options.append(put(el('li'),explained(option,'这项解释已登记，请展开查看原文。'))));row.append(options);}
    else row.append(explained(p.statement,'假设内容已登记，请展开查看原文。'));
    if(p.impact)row.append(put(el('div','decision-impact'),el('strong','','会影响什么'),explained(p.impact,'影响已登记，请展开查看原文。')));
    if(p.rationale)row.append(put(el('div','small-gap'),el('strong','','提出依据'),explained(p.rationale,'提出依据已登记，请展开查看原文。')));
    row.append(el('p','muted small small-gap',item.freeze_gate==='conditional'?'已有可逆假设支持带条件推进；题意仍未解决，需要后续检查。':item.current_errors?.length?'原解释记录仍可回看，但不能视为当前有效依据。':item.status==='open'||item.status==='proposed'?'请在 AI 对话中说明选择与理由，再按项目流程登记。页面不会替你选择。':'选择已记录；是否通过实际检查请查看下方记录。'));
    members.forEach(member=>{const object=byId(member.object_id);if(object)row.append(put(el('div'),objectLink(object,members.length>1?`${questionLabel(member.question)||'相关小问'} · 查看完整记录与依据`:'查看完整记录与依据')));});
    const text=[`请基于最新项目状态，与我讨论${questions}的${ambiguous?'题意解释':'建模假设'}。`,ambiguous?`候选解释：\n${(p.interpretations||[]).map((x,i)=>`${i+1}. ${x}`).join('\n')}`:`假设：${p.statement||''}`,`影响：${p.impact||'尚未登记'}`,p.rationale?`提出依据：${p.rationale}`:'','请比较适用条件与验证方法；目前没有在页面作出选择，请不要把复制提纲当作采用或核验。'].filter(Boolean).join('\n\n');
    const copy=disclosure('与 AI 继续讨论',el('p','muted small','复制到现有 AI 对话后，助手才会收到。'));
    const draft=el('textarea','discussion-text');draft.readOnly=true;draft.value=text;draft.setAttribute('aria-label','可复制的讨论提纲');
    copy.append(draft,button('复制讨论提纲',async()=>{try{await navigator.clipboard.writeText(text);toast('已复制，粘贴到 AI 对话即可继续讨论。');}catch{draft.focus();draft.select();toast('请手动复制已选中的讨论提纲。');}}));row.append(copy);return row;
  }
  function returnSummary(){
    const delta=workbench.changeItems(view,visit);
    if(delta.reset)return null;
    if(!delta.items.length&&!delta.otherChanges)return null;
    const panel=section('自上次已读后的变化');panel.classList.add('return-summary');
    panel.append(el('p','muted small',`对比本浏览器在 ${stamp(visit.checked_at,true)} 留下的阅读标记。只反映本机记录，不代表队友已同步。`));
    const rows=el('ul','return-list');
    const priority={stale:0,result:1,requirement:2,model:3,task:4,other:5};delta.items.sort((a,b)=>(priority[a.kind]??5)-(priority[b.kind]??5));
    delta.items.slice(0,5).forEach(item=>{
      const object=item.object_id?byId(item.object_id):item.task_id&&view.tasks[item.task_id]?taskObject(view.tasks[item.task_id]):item.requirement_id?(()=>{const r=view.status.requirements.rows.find(r=>r.id===item.requirement_id);return r?requirementObject(r):null;})():null;
      if(!object)return;
      const prefix=item.kind==='stale'?'需要重检：':item.kind==='result'?'成果有更新：':item.kind==='model'?'模型方案有更新：':item.kind==='task'?'任务进展有更新：':item.kind==='requirement'?'题目要求有更新：':'项目内容有更新：';
      rows.append(put(el('li'),el('span','',prefix),objectLink(object),badge(stateOf(object),object)));
    });panel.append(rows);
    if(delta.items.length>5)panel.append(el('p','muted small',`另有 ${delta.items.length-5} 项变化，可在本机变化记录和当前各问详情中查看。`));
    if(delta.otherChanges)panel.append(el('p','muted small','还有其他记录或文件变化，请结合本机变化记录与当前结果核对。'));
    if(!visitPersistent)panel.append(el('p','muted small','浏览器未允许保存阅读标记，本次关闭后可能无法继续比较。'));
    panel.append(put(el('div','summary-actions'),button('这批变化已看过',()=>{if(loading)return;rememberVisit();renderPreservingReading();},'button'),button('查看本机变化',()=>navigate('changes'),'object-link')));
    panel.append(el('p','muted small','“已看过”只更新本浏览器的阅读标记，不改变任务、采用或核验状态。'));return panel;
  }
  function showOverview() {
    const f=put(el('div'),heading('项目总览','看清各问进展、已有成果和下一步。'));
    const changes=returnSummary();if(changes)f.append(changes);
    const next=notice('接下来做什么',nextAction(view),'neutral');next.classList.add('next-step');
    const confirmations=pendingConfirmations(view),decisions=workbench.decisionItems(view);
    if(confirmations.length||decisions.length)next.append(button('查看待确认事项',()=>{$('confirmation-list')?.scrollIntoView({block:'start'});},'button'));
    else next.append(button('查看相关工作',()=>navigate(currentProblems(view).length?'results':view.status.current_task&&stateOf(view.tasks[view.status.current_task.id]||view.status.current_task)!=='completed'?'questions':'paper')));
    f.append(next);
    if(decisions.length){const groups=workbench.interpretationGroups(view,decisions),card=group=>decisionCard(group.items[0],group.items),panel=section('需要你判断',groups.length===decisions.length?`${decisions.length} 项已登记事项`:`${groups.length} 项问题 · ${decisions.length} 条各问记录`);panel.id='confirmation-list';panel.classList.add('decision-panel');groups.slice(0,3).forEach(group=>panel.append(card(group)));if(groups.length>3)panel.append(disclosure(`展开其余 ${groups.length-3} 项`,...groups.slice(3).map(card)));f.append(panel);}
    const groups=questionGroups(view),columns=el('div','columns overview-columns'),left=el('div'),right=el('div');
    const questions=section('各小问进展');
    if(groups.length)groups.forEach(g=>questions.append(questionPanel(g)));else questions.append(empty('从题目要求开始','项目还没有记录各小问的要求。完成审题并登记后，这里会显示进展。'));
    left.append(questions);
    const results=currentObjects(view).filter(o=>o.kind==='ResultRecord');
    if(results.length){const panel=section('主要成果');panel.append(objectTable(results));panel.append(button('查看结论、图表与依据',()=>navigate('results'),'object-link small-gap'));left.append(panel);}
    if(confirmations.length){const panel=section('需要你确认');if(!decisions.length)panel.id='confirmation-list';panel.append(blockers(confirmations));right.append(panel);}
    const problems=currentProblems(view),general=(view.status.blockers||[]).filter(x=>!confirmations.includes(x)&&!decisions.some(item=>[`${item.question} 题意歧义待解决或带条件假设：${item.payload.ambiguity_id}`,`${item.question} 假设尚未明确采纳或拒绝：${item.payload.assumption_id}`].includes(x)));
    if(problems.length||general.length){const panel=section('待解决问题');if(general.length)panel.append(blockers(general,true));if(problems.length)panel.append(objectTable(problems.slice(0,5)));if(problems.length>5)panel.append(button(`查看全部 ${problems.length} 项问题`,()=>{filters.status='all';filters.category='all';navigate('results');},'object-link small-gap'));right.append(panel);}
    const affected=problems.filter(o=>stateOf(o)==='stale');
    if(affected.length){const panel=section('变化对当前工作的影响');panel.append(el('p','',`${affected.length} 项当前记录需要重新检查。受影响的结果与论文，应在检查后再继续使用。`));panel.append(button('查看变化记录',()=>navigate('changes'),'object-link small-gap'));right.append(panel);}
    const paper=paperSummary();if(paper)right.append(paper);
    if(view.decisions?.length){const panel=section('项目决策');panel.append(el('p','muted small',`已有 ${view.decisions.length} 条决策记录，可回看当时的选择和理由。`),button('查看已记录的决策',()=>{navigate('changes');$('project-decisions')?.scrollIntoView({block:'start'});},'object-link small-gap'));right.append(panel);}
    if(!left.children.length&&!right.children.length)return f;
    columns.append(left);if(right.children.length)columns.append(right);else columns.classList.add('single-column');f.append(columns);return f;
  }
  function showQuestions() {
    const f=put(el('div'),heading('各问进展','题目要回答什么，当前采用什么方案，还有哪些工作需要完成。'));
    const groups=questionGroups(view);if(!groups.length)f.append(empty('还没有各问记录','完成审题并登记题目要求后，在这里查看各问进展。'));else groups.forEach(g=>f.append(questionPanel(g,true)));
    const assigned=new Set(groups.flatMap(g=>g.tasks.map(idOf))),other=Object.values(view.tasks).filter(t=>!assigned.has(t.id));
    if(other.length)f.append(put(section('其他项目任务'),objectTable(other.map(taskObject))));return f;
  }
  function showResults() {
    const f=put(el('div'),heading('成果与依据','查看结论、结果与图表；需要时再展开计算过程和模型资料。'));
    const comparisons=showComparisons();if(comparisons)f.append(comparisons);
    const controls=el('div','toolbar'),result=el('div'),input=el('input'),count=el('span','results-count');input.type='search';input.placeholder='搜索小问、内容或状态';input.value=filters.query;input.setAttribute('aria-label','搜索成果');
    const categories={results:['ResultRecord','EvidenceMapEntry','ArtifactRecord'],process:['RunRecord','ValidationReport','ValidationPlan'],basis:['ModelSpec','ParameterSet','ProblemContract','DataContract','CodeManifest','RulesLock'],all:null};
    const update=()=>{const query=filters.query.trim().toLocaleLowerCase(),kindsFilter=categories[filters.category];const found=objects().filter(o=>(filters.scope==='all'||o.is_current!==false)&&(!kindsFilter||kindsFilter.includes(o.kind))&&(filters.status==='all'||stateOf(o)===filters.status)&&(!query||[titleOf(o),kinds[o.kind],statusLabel(stateOf(o),o),questionOf(o,view.objects),idOf(o)].join(' ').toLocaleLowerCase().includes(query)));
      count.textContent=`${found.length} 条记录`;result.replaceChildren(found.length?objectTable(found):empty('没有对应记录','可以调整筛选条件。还没有登记的成果会在登记后出现。'));};
    const select=(label,values,key)=>{const s=el('select');s.setAttribute('aria-label',label);values.forEach(([value,text])=>{const option=el('option','',text);option.value=value;s.append(option);});s.value=filters[key];if(s.selectedIndex<0){s.selectedIndex=0;filters[key]=s.value;}s.addEventListener('change',()=>{filters[key]=s.value;update();});return put(el('label'),el('span','',label),s);};
    input.addEventListener('input',()=>{filters.query=input.value;update();});put(controls,put(el('label'),el('span','','查找内容'),input),select('查看内容',[['results','结论、结果与图表'],['process','计算过程与检查'],['basis','模型与数据资料'],['all','全部记录']],'category'),select('状态',[['all','全部状态'],...[...new Set(objects().map(stateOf))].sort().map(s=>[s,statusLabel(s)])],'status'),select('版本范围',[['current','当前记录'],['all','包括旧版本']],'scope'),count);put(f,controls,result);update();return f;
  }
  function showPaper() {
    const s=view.status.submission,f=put(el('div'),heading('论文准备','查看论文、材料和检查情况。'));
    f.append(notice(s.ready?'已具备待提交条件':'正式提交条件尚未满足',s.ready?'请按比赛要求完成实际提交，并保留提交回执。':'已生成、已检查和已提交分别记录，请按下面的实际情况推进。',s.ready?'info':'neutral'));
    if(s.blockers.length)f.append(put(section('还需要完成'),blockers(s.blockers)));
    const all=currentObjects(view),sections=all.filter(o=>o.kind==='PaperSection');if(sections.length)f.append(put(section('论文章节'),objectTable(sections)));
    const exports=all.filter(o=>o.kind==='ArtifactRecord'&&o.payload?.artifact_type==='paper_export');
    if(exports.length){const panel=section('正文导出与来源检查');exports.forEach(o=>panel.append(put(el('div','list-item'),objectLink(o,'查看导出文件与来源'),badge(stateOf(o),o),el('p','muted small',stateOf(o)==='stale'?'来源已变化，请重新导出并检查。':o.payload?.source_readback_passed?'Word 的文字、表格与公式已与登记来源读回核对；排版、比赛要求与最终定稿仍须分别检查。':'此文件已由本地转换后端生成；请核对实际排版与内容。'))));f.append(panel);}
    const documents=usableFiles(all.filter(o=>['PaperSection','DeliveryAudit','DeliveryPackage','ArtifactRecord'].includes(o.kind)),p=>/\.(pdf|docx|zip)$/i.test(p));
    if(documents.length){const panel=section('论文与材料文件');documents.forEach(({file,object},i)=>panel.append(fileRow(file,object,i)));f.append(panel);}
    const checks=all.filter(o=>['DeliveryAudit','DeliveryPackage','SubmissionAudit','SubmissionPackage'].includes(o.kind));if(checks.length)f.append(put(section('材料检查记录'),objectTable(checks)));
    if(!sections.length&&!documents.length&&!checks.length)f.append(empty('论文材料还没有登记','完成论文章节或生成文件后，在项目中登记，再回到这里查看。'));
    f.append(put(section('实际提交进展'),badge(s.state),el('p','muted small small-gap','本页展示已有记录，查看页面不会执行提交。')));return f;
  }
  function showComparisons() {
    const groups=view.comparisons||[];if(!groups.length)return null;
    const comparisonText=value=>plainText(value,String(value??'').replace(opaque,'相关记录'));
    const panel=section('方案比较');
    const conditions={time_grid:'时间网格',information:'可用信息',horizon:'预测或决策时域',boundary:'边界条件',commitments:'已作出的承诺',costs:'费用口径',split:'评价数据划分',budget:'实验预算'};
    groups.forEach(group=>{
      const block=el('div','comparison-group');
      block.append(el('h3','',`${questionLabel(group.question)} · ${comparisonText(group.title)||'已登记的方案比较'}`),el('p','muted small',group.comparable?'当前已核验指标的登记条件一致，可以在本次检查范围内比较。':'暂不能直接比较；请先核对条件或补齐当前有效的检查。'));
      if(group.reasons?.length){const reasons=group.reasons.map(reason=>String(reason).replace(/比较条件不同：(\w+)/,(_,key)=>`比较条件不同：${conditions[key]||key}`).replace('比较来源、单位或方向不同：source_files','比较使用的数据来源不同').replace('比较来源、单位或方向不同：unit','指标单位不同').replace('比较来源、单位或方向不同：direction','指标比较方向不同'));block.append(blockers(reasons));}
      block.append(listRows((group.rows||[]).map(row=>[
        put(el('div'),el('strong','',comparisonText(row.label)),el('p','muted small',hasChinese(row.method)?comparisonText(row.method):'方法说明保留在比较条件中')),
        row.value===null?'未取得指标':String(row.value),row.unit||'尚未声明',badge(row.status),
        put(el('div','small-gap'),objectLink(byId(row.result_id),'查看计算与检查依据'),disclosure('比较条件与策略',...Object.entries(row.context||{}).map(([key,value])=>put(el('p'),el('strong','',`${conditions[key]||key}：`),el('span','',comparisonText(value)))),el('p','small',`方法：${comparisonText(row.method)}；后端：${comparisonText(row.backend)}；指标${row.direction==='lower'?'越小越好':'越大越好'}。`),objectLink(byId(row.model_id),'查看条件的登记来源')))
      ]),['方案','指标值','声明单位','检查状态','依据与比较条件']));
      block.append(el('p','muted small small-gap',comparisonText(group.scope)));panel.append(block);
    });return panel;
  }
  function changeDescription(x,records={},tasks={}) {
    const reason=String(x.reason||x.summary||x.action||'');
    if(reason==='Register evidence-bound paper section')return '更新论文章节，并关联结论依据';
    if(reason==='Audit current paper and delivery evidence')return '检查论文和提交材料';
    if(reason.includes('Context received'))return '登记收到交接内容';
    if(reason.includes('Context adopted'))return '登记采用交接中的内容';
    if(reason.includes('Context verified'))return '登记交接检查结果';
    const taskChange=reason.match(/^任务 (\S+) -> (\S+)$/);
    if(taskChange){const task=tasks[taskChange[1]];return `${task?displayTitle({...task,kind:'Task'},records):'相关任务'}：${statusLabel(taskChange[2])}`;}
    if(reason.startsWith('创建任务 ')){const task=tasks[reason.slice(5)];return task?'安排任务：'+displayTitle({...task,kind:'Task'},records):'安排了一项任务';}
    if(reason.startsWith('登记 ')){const object=(x.objects||[]).map(id=>records[id]).filter(Boolean).at(-1);if(object)return '记录了'+displayTitle(object,records);}
    return plainText(reason,'项目记录发生了更新，可展开查看原文说明。');
  }
  function showChanges() {
    const f=put(el('div'),heading('本机变化记录','这里只展示本机已记录的变化，不表示队友的最新进展。'));
    const list=el('ol','timeline');(view.changes||[]).slice().reverse().forEach(x=>{const description=changeDescription(x,view.objects,view.tasks),row=put(el('li'),el('time','muted small',stamp(x.at||x.timestamp,true)),put(el('div'),el('p','',description)));if(description.includes('原文说明'))row.lastChild.append(originalText(x.reason||x.summary||x.action||''));list.append(row);});
    f.append(list.children.length?list:empty('还没有变化记录','项目发生并登记变化后，这里会保留相应说明。'));
    if(view.decisions?.length){const panel=section('已记录的项目决策');panel.id='project-decisions';panel.append(el('p','muted small','以下是项目登记的选择及理由。记录本身不执行模型采用，也不证明结果已核验。'));view.decisions.slice().reverse().forEach((decision,index)=>{const item=put(el('article','list-item'),el('h3','',`决策记录 ${view.decisions.length-index}`),el('p','muted small',stamp(decision.at)),explained(decision.decision,'决策内容已登记，请查看原文。'),put(el('div','small-gap'),el('strong','','选择理由'),explained(decision.reason,'选择理由已登记，请查看原文。')));if(decision.actor)item.append(originalText(String(decision.actor),'查看记录署名（未经身份认证）'));const files=decision.evidence||[];if(files.length)item.append(el('p','muted small',`登记时绑定了 ${files.length} 个依据文件；文件现状及适用性需另行核对。`));panel.append(item);});f.append(panel);}
    if(Object.keys(view.members||{}).length)f.append(disclosure('已登记的交接情况',el('p','muted small','以下只代表本机保存的接收、采用和检查记录，无法确认远程成员的最新情况。'),...Object.entries(view.members).map(([name,record])=>put(el('div','list-item'),el('h3','',roles[name]||(/\p{Script=Han}/u.test(name)?plainText(name):'项目成员')),el('p','',`收到更新 ${record.receipts?.length||0} 次；采用 ${record.adoptions?.length||0} 次；检查 ${record.verifications?.length||0} 次。`)))));
    return f;
  }
  function renderIdentity() {
    const identity=view.identity,name=projectName(identity),p=identity.problem||{};$('workspace-name').textContent=name;document.title=name+' · 建模工作台';
    const rows=put(el('div','identity-main'),el('strong','',name),el('span','',`${modeLabel(p.evaluation_mode)} · 本机项目记录 · 读取于 ${stamp(view.checked_at,true)}`));
    if(p.deadline_iso){const deadline=new Date(p.deadline_iso);if(!Number.isNaN(deadline.valueOf()))rows.append(el('span','',`截止时间：${stamp(p.deadline_iso)}`));}
    $('identity').replaceChildren(rows);$('connection-label').textContent='已读取本机记录';$('notification').replaceChildren();
    if(identity.demo)$('notification').append(notice('界面演示','以下是演示内容，没有连接真实项目。','neutral'));
    else if(p.evaluation_mode&&p.evaluation_mode!=='formal_contest')$('notification').append(el('p','project-mode','练习或研究结果不能直接作为正式参赛已就绪的证明。'));
    $('diagnostic').disabled=false;
  }
  function render() {if(!view||loading)return;renderedPage=page;pages.forEach(p=>{const b=$('nav-'+p.id);if(p.id===page)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});renderIdentity();$('content').replaceChildren(page==='overview'?showOverview():page==='questions'?showQuestions():page==='results'?showResults():page==='paper'?showPaper():showChanges());}
  const allNodes=(root,selector)=>Array.from(root.querySelectorAll?.(selector)||[]);
  function readingState(root){
    const counts=new Map(),open=new Set();
    allNodes(root,'details').forEach(node=>{const base=(node.closest?.('[data-question]')?.dataset.question||'')+'|'+node.querySelector('summary')?.textContent;const n=counts.get(base)||0;counts.set(base,n+1);if(node.open)open.add(base+'|'+n);});
    const active=document.activeElement,focus=active&&root.contains?.(active)?{id:active.id,object:active.dataset?.objectId,file:active.dataset?.filePath,label:active.getAttribute?.('aria-label'),start:active.selectionStart,end:active.selectionEnd}:null;
    return {open,focus,scroll:root.scrollTop};
  }
  function restoreReading(root,saved){
    const counts=new Map();allNodes(root,'details').forEach(node=>{const base=(node.closest?.('[data-question]')?.dataset.question||'')+'|'+node.querySelector('summary')?.textContent;const n=counts.get(base)||0;counts.set(base,n+1);node.open=saved.open.has(base+'|'+n);});
    const f=saved.focus;if(f){const target=allNodes(root,'button,input,select,textarea,summary').find(node=>f.id?node.id===f.id:f.object?node.dataset.objectId===f.object:f.file?node.dataset.filePath===f.file:f.label?node.getAttribute('aria-label')===f.label:false);target?.focus({preventScroll:true});if(f.start!==null&&f.start!==undefined)try{target?.setSelectionRange(f.start,f.end);}catch{/* Select inputs have no selection range. */}}
    root.scrollTop=saved.scroll;
  }
  function renderPreservingReading(){const root=$('content'),saved=readingState(root),y=window.scrollY||0;render();restoreReading(root,saved);window.scrollTo?.({top:y,behavior:'instant'});}
  function freshDetail(old){
    if(old.kind==='Task')return view.tasks[idOf(old)]?taskObject(view.tasks[idOf(old)]):null;
    if(old.kind==='Requirement'){const row=view.status.requirements.rows.find(row=>row.id===idOf(old));return row?requirementObject(row):null;}
    if(old.is_current!==false&&old.key){const latest=currentObjects(view).find(o=>o.key===old.key);if(latest)return latest;}
    return byId(idOf(old))||null;
  }
  function updateReader(){
    if(!$('detail').open)return;
    const saved=readingState($('detail-body')),scroll=$('detail').scrollTop,previous=detailStack.at(-1),current=previous&&freshDetail(previous);
    detailStack=detailStack.map(freshDetail).filter(Boolean);
    if(current){openDetail(current,null,true,true);restoreReading($('detail-body'),saved);$('detail-refresh-status').textContent='已重新核对当前记录，详情已更新；展开的文件内容请重新读取。';}
    else{detailStack=[];const title=el('h1','','这项记录暂不可用');title.id='detail-heading';$('detail-body').replaceChildren(title,el('p','','本次项目记录中已没有这项内容，请关闭详情后查看当前工作。'));$('detail-back').disabled=true;$('detail-refresh-status').textContent='原内容已撤下，未继续作为当前结果显示。';}
    $('detail-refresh-status').hidden=false;$('detail').scrollTop=scroll;
  }
  function navigate(next) {next=aliases[next]||next;if(!pages.some(p=>p.id===next)&&next!=='changes')return;page=next;history.replaceState(null,'','#'+next);render();$('content').focus({preventScroll:true});}
  function fileLabel(path,index=0) {
    const name=String(path).split(/[\\/]/).at(-1),known={'driver.py':'计算程序','checker.py':'独立检查程序','run_context.json':'本次计算设置','receipt.json':'执行记录','sealed-report.json':'检查报告','validation.json':'检查结果','stdout.log':'运行过程','stderr.log':'错误记录','traffic.json':'交通模拟数据','comparison.csv':'方案比较表','technical_summary.md':'技术说明','experiment_summary.json':'计算结果汇总','healthy_comparison.csv':'正常情景比较表','assignment_search.csv':'候选方案比较表','table_manifest.json':'结果表清单','official_parameters.json':'题目给定参数','model_description.json':'模型说明','kernel_tests.json':'算法检查结果','manuscript.md':'论文原稿','results.md':'计算结果章节','introduction.md':'论文引言','healthy.csv':'正常情景结果表','fault.csv':'故障情景结果表','sensitivity.csv':'敏感性分析表','healthy.png':'正常情景图表','fault.png':'故障情景图表','supporting-materials.zip':'配套材料压缩包','note.md':'文字说明'};
    if(known[name])return known[name];if(hasChinese(name))return plainText(name);const q=name.match(/^Q(\d+)\.md$/i);if(q)return `第${Number(q[1])}问的论文原稿`;const ext=name.split('.').at(-1).toLowerCase();return `${({csv:'数据表',xls:'电子表格',xlsx:'电子表格',pdf:'最终文档',docx:'论文原稿',py:'程序文件',md:'说明文档',json:'数据记录',log:'运行日志',png:'图片',svg:'图片',zip:'材料压缩包'})[ext]||'相关文件'} ${index+1}`;
  }
  function fileRow(file,object,index=0) {
    const item=el('div','list-item file-row'),name=fileLabel(file.path,index),canRead=/\.(txt|log|md|json|csv|py|yaml|yml|tex)$/i.test(file.path)&&!(file.byte_size>262144);
    const copyLocation=()=>{navigator.clipboard.writeText(file.path).then(()=>toast('已复制项目内的文件位置。')).catch(()=>toast('复制未成功，可导出诊断记录查看文件位置。'));};
    put(item,el('strong','',name),el('p','muted small',stateHint(object)));
    if(canRead){const b=button('查看内容',()=>{if(!$('detail').open)openDetail(object,b);openFile(file.path,name);},'object-link');b.dataset.filePath=file.path;item.append(b);}
    else item.append(el('p','muted small','此格式暂不支持在工作台预览，请在电脑上打开。'));
    item.append(button('复制文件位置',copyLocation,'button quiet'));return item;
  }
  function toast(text) {$('toast').textContent=text;setTimeout(()=>{$('toast').textContent='';},2500);}
  function numericSources(o) {
    const panel=disclosure('数字来源与检查依据',el('p','muted small','数字可与已登记结果对应，不表示自然语言推论、因果关系或全局最优已获证明。名称和单位是模型声明，仍需领域检查。'));
    const request=metricHelpRequest(o);
    if(request){const help=disclosure('指标说明不完整，如何补充？',el('p','muted small','将下面的请求交给 AI，核对含义、单位和适用范围。这里只复制说明，不会在页面中修改模型。'),el('pre','source-content',request));help.append(button('复制补充说明请求',()=>{if(!navigator.clipboard?.writeText){toast('当前浏览器不支持直接复制，请选取上方文字。');return;}navigator.clipboard.writeText(request).then(()=>toast('已复制，粘贴到当前 AI 对话即可。')).catch(()=>toast('复制未成功，请选取上方文字。'));},'button quiet'));panel.append(help);}
    if(o.is_current===false)panel.append(notice('这是旧版本','下列来源只用于回看，不能当作当前可用的结果。','neutral'));
    else if(errorsOf(o).length||stateOf(o)==='stale')panel.append(notice('当前依据需要重检','依据或文件已经变化，请完成检查后再使用这些数字。'));
    const results=new Map();
    const metricDescription=(metric,index)=>{
      const row=metricRows({metric_details:{items:[metric]}})[0],detail=put(el('div','list-item'),el('h3','',row[0].replace('指标 1',`指标 ${index+1}`)),el('p','',`记录值：${row[1]}；声明单位：${row[2]}`));
      if(metric.declaration_status==='conflicting')detail.append(el('p','muted small','关联模型的指标声明不一致，未选择其中一种解释。'));
      if(metric.label&&!hasChinese(metric.label))detail.append(originalText(metric.label,'查看指标含义原文'));
      const scope=metric.scope||metric.result_scope;if(scope)detail.append(put(el('div','small-gap'),el('strong','','适用范围'),explained(scope,'适用范围已登记，请查看原文。')));else detail.append(el('p','muted small','适用范围尚未登记。'));
      if(metric.metadata_source_ids?.length)detail.append(disclosure('查看名称和单位的声明来源',...metric.metadata_source_ids.map(resolve)));
      if(metric.metric_path)detail.append(originalText(metric.metric_path,'查看指标在结果中的位置'));
      return detail;
    };
    if(o.kind==='ResultRecord'){
      results.set(idOf(o),o);
      const items=o.metric_details?.items||[];items.slice(0,20).forEach((metric,index)=>panel.append(metricDescription(metric,index)));
      if(!items.length)panel.append(el('p','muted small','尚未读取到明确的指标说明，请查看完整结果及关联模型。'));
      if(items.length>20||o.metric_details?.truncated)panel.append(el('p','muted small','此处展示前 20 项来源说明，完整字段保留在结果数据与诊断记录中。'));
    }else{
      const provenance=o.numeric_provenance;
      if(!provenance||provenance.error)panel.append(el('p','muted small','本次未能重新建立数字来源对应关系，请检查关联结果；未采用历史缓存作为依据。'));
      if(provenance?.unbound_numbers?.length)panel.append(el('p','muted small','尚未找到数值来源：'+provenance.unbound_numbers.join('、')));
      (provenance?.bindings||[]).forEach(binding=>{
        const block=put(el('div','list-item'),el('h3','',`文中数字：${binding.text}`));
        if(binding.sources.length>1)block.append(el('p','muted small','多个指标包含相同数值，数字匹配本身不能确定语义；请核对实际引用的是哪一项。'));
        binding.sources.forEach((source,index)=>{const result=byId(source.result_id);if(result){results.set(source.result_id,result);block.append(put(el('div','row-inline'),objectLink(result),badge(stateOf(result),result)));}if(!source.current)block.append(el('p','muted small','此来源不是当前已检查的结果，仅供历史追溯。'));if(source.metric)block.append(metricDescription(source.metric,index));else block.append(el('p','muted small','指标位置存在歧义或缺少说明，未据此推断单位与含义。'));});
        if(binding.display_contract){const contract=binding.display_contract;block.append(el('p','muted small',`显示方式：${contract.format==='percent'?'比例转百分数':'十进制'}，保留 ${contract.decimal_places} 位小数；${contract.rounding==='half_even'?'取最近值，中点取偶数':'取最近值，中点远离零'}。`),el('p','muted small',`原始数值：${contract.raw_value}；展示数值：${contract.display_value}。舍入不等于误差验证。`));}
        panel.append(block);
      });
      if(provenance&&!provenance.bindings?.length&&!provenance.error)panel.append(el('p','muted small','本条记录没有已建立来源对应的数值。'));
    }
    results.forEach(result=>{
      const related=put(section('对应的运行与检查'),el('p','muted small',stateHint(result)));
      (result.dependencies||[]).filter(id=>['RunRecord','ValidationReport'].includes(byId(id)?.kind)).forEach(id=>related.append(put(el('div','row-inline small-gap'),resolve(id),badge(stateOf(byId(id)),byId(id)))));
      if(result.files?.length)related.append(disclosure('查看结果文件',...result.files.map((file,index)=>fileRow(file,result,index))));panel.append(related);
    });
    return panel;
  }
  function detailFacts(container,o) {
    const p=o.payload||o,def=p.definition||p,dl=el('dl'),pairs=[['内容类型',kinds[o.kind]||'项目记录'],['所属小问',questionOf(o,view.objects)],['记录时间',o.created_at?stamp(o.created_at):null]];
    if(o.kind==='Task')pairs.push(['负责角色',roles[p.role]||'负责人未记录']);
    pairs.filter(([,value])=>value).forEach(([key,value])=>put(dl,el('dt','',key),el('dd','',value)));container.append(dl);
    if(['AmbiguityEntry','AssumptionEntry'].includes(o.kind)){
      const row=(view.status.interpretations||[]).find(item=>item.object_id===idOf(o));
      if(row)container.append(decisionCard({...row,object_id:null}));
      else container.append(el('p','muted small','以下为历史解释记录，不代表当前选择。'),originalText(JSON.stringify(p,null,2),'查看历史记录原文'));
      if(p.resolution)container.append(put(section('已登记的解释'),explained(p.resolution)));
      if(row?.mathematical_validation==='pending')container.append(notice('假设已采用，仍待实际核验','请按预先登记的检查方案验证；采用本身不证明假设成立。'));
      if(row?.mathematical_validation==='validated_checks')container.append(el('p','muted small','已完成登记的实际检查；不代表假设在所有情景下成立。'));
      if(p.source_anchor)container.append(originalText(p.source_anchor,'查看题面出处'));
    }
    if(o.kind==='Requirement') {
      if(def.requested_action)container.append(put(section('需要完成什么'),explained(def.requested_action,'本项要求尚未提供中文说明，请查看原文。')));
      const context=requirementContext(def);if(context)container.append(put(section('适用情景'),el('p','',context)));
      if(def.outputs?.length)container.append(put(section('需要交付的内容'),...def.outputs.map((output,i)=>el('p','',outputLabel(output,i)))));
      if(def.source_anchor)container.append(originalText(def.source_anchor,'查看题面出处'));
    }
    if(o.kind==='ModelSpec'){
      if(p.solver?.method)container.append(put(section('采用的方法'),explained(p.solver.method,'方法已登记，请展开查看原文说明。')));
      const decision=p.method_decision?.candidates?.find(c=>c.decision==='selected');if(decision?.reason)container.append(put(section('选择这个方案的原因'),explained(decision.reason,'选择理由已记录，请展开查看原文说明。')));
      if(p.assumptions?.length)container.append(put(section('主要假设'),blockers(p.assumptions.map(a=>typeof a==='string'?a:a.description||a.statement||a.text||JSON.stringify(a)))));
      if(p.constraints?.length)container.append(disclosure('模型需要满足的限制',blockers(p.constraints.map(c=>typeof c==='string'?c:c.expression||c.description||JSON.stringify(c)))));
    }
    if(o.kind==='Task'&&p.acceptance)container.append(put(section('完成要求'),explained(p.acceptance)));
    if(p.metrics){const rows=metricRows(o);if(rows.length){container.append(put(section('已登记数值'),listRows(rows.slice(0,20),['指标含义','记录值','声明单位']),el('p','muted small small-gap','名称和单位来自模型中的明确声明；尚未登记时不根据字段名猜测。声明本身不代表单位已通过科学核验。')));if(rows.length>20||o.metric_details?.truncated)container.append(el('p','muted small','此处按原记录顺序展示前 20 项，完整数据可在下方展开。'));}container.append(disclosure('查看完整结果数据',el('p','muted small','数据保留原始字段和数值，包含所有已记录情景。'),el('pre','source-content',JSON.stringify(p.metrics,null,2))));container.append(numericSources(o));}
    if(o.kind==='EvidenceMapEntry')container.append(numericSources(o));
    if(o.kind==='ValidationReport'&&Array.isArray(p.checks)){const panel=section('检查项目与预定标准');panel.append(el('p','muted small','以下判定来自已运行的检查程序；页面展示原记录，不另行推导数学结论。'));validationRows(p).forEach(check=>{const item=put(el('div','list-item'),el('h3','',check.name),badge(check.status),el('p','muted small',check.predeclared?'运行前已声明的标准':'标准来源尚待确认'),check.criterion?explained(check.criterion,'检查标准已登记，请展开查看原文。'):el('p','muted small','检查标准尚未登记。'));if(check.actual!==undefined)item.append(disclosure('查看实际观测值（原始记录）',el('pre','source-content',JSON.stringify(check.actual,null,2))));if(check.evidence.length)item.append(disclosure('查看本次检查依据',...check.evidence.map((path,index)=>{const source=objects().find(obj=>obj.files?.some(file=>file.path===path));return source?objectLink(source,`${fileLabel(path,index)} · 查看来源`):el('p','muted small',`${fileLabel(path,index)}：未读取到关联记录。`);})));panel.append(item);});container.append(panel);}
    if(p.claim)container.append(put(section('结论内容'),explained(p.claim,'结论尚未提供中文说明，请查看原文。')));
    if(p.scope)container.append(put(section('适用范围'),explained(p.scope,'使用范围已记录，请展开查看原文。')));
    if(p.limitations?.length)container.append(put(section('使用这些结果时需要注意'),blockers(p.limitations)));
    if(o.kind==='ParameterSet'){const parameters=parameterRows(p);if(parameters.length)container.append(put(section(o.is_current===false?'此版本参数':'当前参数'),listRows(parameters,['参数含义','取值','单位'])));}
  }
  function openDetail(o,source,back=false,preserve=false) {
    if(loading&&!preserve){toast('正在重新核对，请稍候再打开记录。');return;}
    const d=$('detail');if(!d.open){opener=source;detailStack=[];}if(!back)detailStack.push(o);const container=$('detail-body');container.replaceChildren();const header=el('h1','',titleOf(o));header.id='detail-heading';put(container,badge(stateOf(o),o),header,el('p','detail-summary',stateHint(o)));
    const guide=recheckGuide(o,view);
    if(guide){const panel=section('为什么需要重新检查');if(guide.causes.length)guide.causes.forEach(cause=>panel.append(put(el('div','list-item'),el('p','',cause.message),put(el('div','row-inline small-gap'),resolve(cause.id),cause.latest?objectLink(byId(cause.latest),'查看更新后的依据'):null))));else panel.append(el('p','muted small','当前记录未通过有效性检查，具体原因见下方诊断；这里不推断未确认的根因。'));panel.append(el('p','',guide.next));if(guide.downstream.length)panel.append(disclosure('哪些后续内容使用了它',...guide.downstream.map(resolve)));container.append(panel);}
    if(errorsOf(o).length)container.append(guide?.causes.length?disclosure(`查看全部重检诊断（${errorsOf(o).length} 条）`,blockers(errorsOf(o))):put(section('需要处理'),blockers(errorsOf(o))));detailFacts(container,o);
    const relation=(title,items,lookup)=>{if(!items?.length)return;const chain=el('div','chain');items.forEach(id=>chain.append(lookup(id)));container.append(disclosure(title,chain));};
    if(o.kind==='Task'){relation('先完成的任务',o.depends_on,id=>view.tasks[id]?objectLink(taskObject(view.tasks[id])):el('span','muted','前置任务尚未读取到'));relation('这项任务的产出',o.outputs,resolve);}
    relation('依据哪些内容',o.dependencies,resolve);relation('哪些内容用到了它',objects().filter(x=>(x.dependencies||[]).includes(idOf(o))&&x.is_current!==false).map(idOf),resolve);
    if(o.files?.length){const files=section('相关文件');const seen=new Set();o.files.forEach((file,i)=>{if(!seen.has(file.path)){files.append(fileRow(file,o,i));seen.add(file.path);}});container.append(disclosure('查看相关文件',files));}
    container.append(diagnostic(o));$('detail-back').disabled=detailStack.length<2;if(!d.open)d.showModal();if(!preserve){$('detail-refresh-status').hidden=true;d.scrollTop=0;$('detail-close').focus();}
  }
  async function openFile(path,name) {
    if(loading||!view){toast('正在重新核对，请稍候再读取文件。');return;}
    const snapshotId=view.snapshot_id,fileToken=fileGeneration,body=$('detail-body'),node=put(el('section','large-gap'),el('h2','',name),el('p','muted small','正在检查并读取文件…'));node.dataset.pendingFile='true';body.append(node);node.scrollIntoView({block:'nearest'});
    try {const result=await window.CopilotData.readFile(view,path);if(fileToken!==fileGeneration||!node.isConnected)return;if(!view||view.snapshot_id!==snapshotId)throw new Error('项目已刷新，请重新打开文件。');node.dataset.pendingFile='false';node.replaceChildren(el('h2','',name),el('p','muted small','以下为文件原文，英文、程序代码和数据保持原样。'),el('pre','file-content',result.content));if(Object.keys(result.current_errors||{}).length)node.prepend(notice('文件来源需要重新检查','关联内容已发生变化，请在检查后再使用其中的结果。'));}
    catch(error){if(fileToken!==fileGeneration||!node.isConnected)return;node.dataset.pendingFile='false';node.replaceChildren(notice('暂时无法打开文件','请刷新项目后重试；如果仍然失败，可导出诊断记录查看原因。','bad'),diagnostic({message:error.message}));}
  }
  async function refresh() {
    clearTimeout(pollTimer);const token=++generation;fileGeneration++;loading=true;window.CopilotInteraction?.suspend();$('refresh').disabled=true;$('diagnostic').disabled=true;$('connection-label').textContent='正在重新核对';
    for(const node of allNodes($('detail-body'),'[data-pending-file="true"]')){node.dataset.pendingFile='false';node.replaceChildren(el('p','muted small','项目正在刷新，请稍后重新打开文件。'));}
    const pending='正在重新核对。下方暂保留上次读取的内容，请等待更新后再判断。';
    $('refresh-status').textContent=pending;$('refresh-status').hidden=!view;
    if($('detail').open){$('detail-refresh-status').textContent=pending;$('detail-refresh-status').hidden=false;}
    if(!view){$('identity').replaceChildren(el('span','','正在读取本机项目…'));$('content').replaceChildren(put(el('div','loading'),el('h2','','正在读取项目'),el('p','','检查工作进度和相关文件，请稍候。'),el('div','skeleton'),el('div','skeleton short')));}
    try {
      const next=await window.CopilotData.load();if(token!==generation)return;
      if(!next||next.read_only!==true||!next.project_id||!Number.isInteger(next.revision)||!next.state_hash||!next.checked_at||!next.status?.requirements||!next.status?.submission||!next.objects||!next.tasks)throw new Error('项目记录不完整，请检查项目后重试。');
      const previous=view,switching=previous&&previous.project_id!==next.project_id;
      const comparable=v=>JSON.stringify([v.project_id,v.state_hash,v.authority_file_sha256,v.file_observation_hash,v.identity,v.status,v.objects,v.tasks,v.requirements,v.members,v.decisions,v.changes]);
      const changed=!previous||comparable(previous)!==comparable(next);
      observeVisit(next);view=next;loading=false;
      if(switching){if($('detail').open)$('detail').close();filters.query='';filters.status='all';filters.scope='current';filters.category='results';render();}
      else if(changed||renderedPage!==page){renderPreservingReading();if(changed)updateReader();else $('detail-refresh-status').hidden=true;}
      else{renderIdentity();$('detail-refresh-status').hidden=true;}
      window.CopilotInteraction?.observe(interactionContext(view));
    }
    catch(error){if(token!==generation)return;loading=false;view=null;if($('detail').open)$('detail').close();$('detail-body').replaceChildren();$('notification').replaceChildren();$('workspace-name').textContent='项目暂不可用';$('identity').textContent='尚未读取到当前项目';$('connection-label').textContent='读取失败';const failure=empty(error.name==='OfflineError'?'无法连接本机项目':'暂时无法读取项目',plainText(error.message,'请检查本地项目服务是否仍在运行，然后重新读取。'));failure.append(button('重新读取',refresh));$('content').replaceChildren(heading('项目暂时不可用','已收起上次的内容，避免把旧结果误认为最新情况。'),failure,diagnostic({message:error.message}));}
    finally{if(token===generation){$('refresh').disabled=false;$('refresh-status').hidden=true;schedulePoll();}}
  }
  function schedulePoll(){clearTimeout(pollTimer);if(document.visibilityState==='hidden')return;pollTimer=setTimeout(()=>{if(!loading&&document.visibilityState!=='hidden')refresh();},15000);pollTimer?.unref?.();}
  // Returning to this local workbench is a fresh observation, not a cached status.
  // visibilitychange and focus often arrive together; consume each departure once.
  let wasAway=document.visibilityState==='hidden'||(typeof document.hasFocus==='function'&&!document.hasFocus());
  const refreshOnReturn=()=>{if(wasAway&&document.visibilityState!=='hidden'){wasAway=false;refresh();}};
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){wasAway=true;clearTimeout(pollTimer);}else refreshOnReturn();});
  window.addEventListener('blur',()=>{wasAway=true;});
  window.addEventListener('focus',refreshOnReturn);
  window.addEventListener('pageshow',event=>{if(event.persisted){wasAway=true;refreshOnReturn();}});
  pages.forEach(p=>{const b=button('',()=>navigate(p.id),'nav-button');b.id='nav-'+p.id;put(b,icon(p.id),el('span','',p.name));$('navigation').append(b);});
  $('changes-link').addEventListener('click',()=>navigate('changes'));
  window.addEventListener('copilot-interaction-updated',refresh);
  $('diagnostic').addEventListener('click',()=>{if(view)diagnostic(view).click();});
  $('refresh').addEventListener('click',refresh);$('detail-close').addEventListener('click',()=>$('detail').close());$('detail-back').addEventListener('click',()=>{if(!loading&&detailStack.length>1){detailStack.pop();openDetail(detailStack.at(-1),null,true);}});$('detail').addEventListener('close',()=>{detailStack=[];if(opener?.isConnected)opener.focus();});window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)));window.addEventListener('copilot-preview-change',refresh);const initial=aliases[location.hash.slice(1)]||location.hash.slice(1);if(pages.some(p=>p.id===initial)||initial==='changes')page=initial;refresh();
})();
