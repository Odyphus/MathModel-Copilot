"""Register a full historical paper against the actual fresh benchmark state."""
from __future__ import annotations
import copy, hashlib, json, shutil, sys, time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

from paper_paths import HERE, PRODUCT, PROJECT, RULES
sys.path.insert(0, str(PRODUCT / 'scripts'))
from copilot_runtime import Runtime, bind_file, usable
import copilot_domain as domain
from copilot_delivery import Delivery
from copilot_packs import load_pack
from copilot_store import digest
from render_ai_usage import validate_entries, render_cumcm_use_statement, render_cumcm_markdown

def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()
def fmt(value, places=2): return format(Decimal(str(value)).quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_EVEN),'f')

def main():
    rt=Runtime(PROJECT); delivery=Delivery(PROJECT); rev=lambda:rt.read()['copilot']['revision']
    report=json.loads((PROJECT/'benchmark_report.json').read_text(encoding='utf-8'))
    ids=report['objects']; metrics=ids['Q2']['metrics']; now=datetime.now(timezone.utc).isoformat()
    (PROJECT/'paper').mkdir(exist_ok=True)
    if not rt.read()['copilot'].get('rules_lock'):
        if RULES != PROJECT/'rules':
            shutil.copytree(RULES,PROJECT/'rules',dirs_exist_ok=True)
        snapshots=json.loads((PROJECT/'rules/fetch-record.json').read_text(encoding='utf-8'))
        for row in snapshots: row['path']='rules/'+row['path']
        delivery.lock_rules(rev(),load_pack('cumcm'),2018,2026,'historical_benchmark',snapshots,'Codex agent_evaluator')
    if not rt.read()['compliance'].get('ai_usage'):
        rt.log_ai(rev(),{'entry':{
            'tool':'OpenAI Codex','model':'当前执行会话模型，精确型号未独立核实','version':'未获得可独立核验的服务版本号',
            'used_at':now,'use_stage':'历史复现、结果整理、论文制作和自动审计',
            'purpose':'代码审查、结果整理与论文辅助编写','paper_sections':['全文与源程序附录'],
            'human_review':'尚未完成人工终审；本次核验由 AI agent 执行，不能替代团队人工核验。',
            'process_summary':'在新工作区重跑调度代码；独立复验运行结果；由已核验结果生成主张、表格和图；制作 Word 并回读来源。PDF 导出和逐页检查是否完成由另存的本轮渲染记录证明。',
            'adoption':'保留已绑定真实运行来源的结果和说明；未将候选策略称为全局最优，未声称正式参赛、人工签字或取得官方回执。',
            'evidence':['benchmark_report.json']}})
    cp=rt.read()['copilot']; lock=cp['current']['rules.lock']
    # A registry identifies real local source bytes. It is still subject to
    # the existing DOCX bookmark/citation check; this is not a human signoff.
    sources=[
      ('RGV_PROBLEM','全国大学生数学建模竞赛组委会 2018 年 B 题 智能 RGV 的动态调度策略 英文官方题面',
       'assets/CUMCM-2018-Problem-B-English.pdf','https://en.mcm.edu.cn/html_en/node/b4184fa60b0e32c59e451c1e351d321d.html'),
      ('AI_TOOL','OpenAI Codex 本次会话 AI 工具 具体模型及服务版本未独立核实',
       'paper/ai-ledger.json','https://openai.com/codex/'),
    ]
    write(PROJECT/'paper/ai-ledger.json',rt.read()['compliance']['ai_usage'])
    refs=[]; citations=[]
    for number,(key,title,path,url) in enumerate(sources,1):
        record={'reference_id':key,'title':title,'source_url':url,'local_path':path,
                'sha256':sha(PROJECT/path),'verification':'Read actual local official problem PDF or current AI session ledger; agent evaluation, not human review.',
                'verified_at':now,'actor_kind':'agent_evaluator'}
        record_path=PROJECT/f'paper/reference-{key}.json'
        if record_path.exists():record=json.loads(record_path.read_text(encoding='utf-8'))
        else:write(record_path,record)
        refs.append({'reference_id':key,'number':number,'title':title,'url':url,'bibliography_anchor':f'BIB_{key}',
          'verification_status':'verified','adoption_status':'adopted','verification_record_hash':digest(record)})
        citations.append({'citation_id':'CITE_'+key,'reference_id':key,'claim_id':ids['Q1']['claim'],
                          'number':number,'anchor':'CITE_'+key})
    registry={'schema_version':'1.0','record_type':'reference_registry','citation_style':{'marker_format':'[{number}]'},
              'no_external_sources':False,'references':refs,'citations':citations}
    registry_path=PROJECT/'paper/reference_registry.json'
    if registry_path.exists():registry=json.loads(registry_path.read_text(encoding='utf-8'))
    else:write(registry_path,registry)
    registry_id=rt.read()['copilot']['current'].get('paper.references')
    if registry_id is None:
        registry_id=rt.register(rev(),'ArtifactRecord','paper.references',{'artifact_type':'reference_registry','path':'paper/reference_registry.json'},
          dependencies=[ids['Q1']['data']],files=['paper/reference_registry.json'])['result']['object_id']
    claims={}; text={}; claim_ids=[ids['Q2']['claim']]
    template=copy.deepcopy(cp['objects'][ids['Q2']['claim']]['payload'])
    def claim(key,sentence,displays=()):
        began=time.perf_counter()
        p=copy.deepcopy(template); p.update(claim_id='PAPER-'+key,claim=sentence,claim_type='numerical',paper_anchor='paper/results.md',display_contracts=list(displays))
        p.pop('status',None)
        current=rt.read()['copilot'];existing=current['current'].get(p['claim_id'])
        expected_entry=domain.EvidenceMapEntry.from_dict(p);expected_entry.status='pass'
        canonical=expected_entry.to_dict();canonical.pop('status',None)
        previous=copy.deepcopy(current['objects'].get(existing,{}).get('payload',{}));previous.pop('status',None)
        if existing and previous==canonical and usable(PROJECT,current,existing,verified=True):
            out={'claim_id':existing,'status':'verified'}
        else:out=rt.claim(rev(),p,[ids['Q2']['result']])['result']
        if out['status']!='verified': raise RuntimeError(out)
        print(f"Claim {key}: {out['claim_id']}; {time.perf_counter()-began:.3f}s",flush=True)
        claims[key]=out['claim_id'];text[key]=sentence;claim_ids.append(out['claim_id'])
        return sentence+' [[claim:'+out['claim_id']+']]'
    def display(pointer,value,places=2,format_kind='decimal'):
        shown=fmt(Decimal(str(value))*(100 if format_kind=='percent' else 1),places)+('%' if format_kind=='percent' else '')
        return {'version':'0.1','result_id':ids['Q2']['result'],'metric_path':pointer,'raw_value':str(value),
                'display_value':shown,'format':format_kind,'decimal_places':places,'rounding':'half_even'}
    paragraphs={}
    counts=metrics['delivered_counts']
    paragraphs['healthy']=claim('HEALTHY',f"正常单工序下，组一、组二、组三分别交付 {counts['g1_single_healthy']}、{counts['g2_single_healthy']}、{counts['g3_single_healthy']} 件；正常双工序有限候选策略分别交付 {counts['g1_two_healthy']}、{counts['g2_two_healthy']}、{counts['g3_two_healthy']} 件。")
    paragraphs['validation']=claim('VALIDATION',f"独立验证器核对 {metrics['commands_checked']} 条调度命令与 {metrics['numeric_cells_checked']} 个表格数字单元格；运行内部完成 {metrics['feasibility_checks']} 次可行性复验。")
    stat_rows=[];stat_claims=[];compare_rows=[];compare_claims=[]
    labels=['组一单工序','组一双工序','组二单工序','组二双工序','组三单工序','组三双工序']
    for i,row in enumerate(metrics['fault_statistics']):
        a=row['selected']; lo,hi=a['mean_ci95_normal']; label=labels[i]
        pointers=[('mean',a['mean']),('sd',a['sd']),('mean_ci95_normal/0',lo),('mean_ci95_normal/1',hi)]
        contracts=[display(f'/fault_statistics/{i}/selected/{key}',value) for key,value in pointers]
        sentence=f"{label}故障样本均值 {fmt(a['mean'])} 件，样本标准差 {fmt(a['sd'])} 件，最小值 {a['minimum']} 件，最大值 {a['maximum']} 件，均值正态近似区间为 {fmt(lo)} 至 {fmt(hi)} 件。"
        stat_claims.append(claim('FAULT-'+str(i),sentence,contracts))
        stat_rows.append([label,fmt(a['mean']),fmt(a['sd']),str(a['minimum']),str(a['maximum']),fmt(lo)+' 至 '+fmt(hi)])
        b=row['baseline'];prefix=row['prefix16']
        sentence=f"{label}的所选配置、对照配置及前缀样本均值分别为 {fmt(a['mean'])}、{fmt(b['mean'])}、{fmt(prefix['mean'])} 件。"
        compare_claims.append(claim('COMPARE-'+str(i),sentence,[display(f'/fault_statistics/{i}/{part}/mean',value['mean']) for part,value in [('selected',a),('baseline',b),('prefix16',prefix)]]))
        compare_rows.append([label,fmt(a['mean']),fmt(b['mean']),fmt(prefix['mean'])])
    sens_rows=[]; sens_claims=[]
    # A compact subset is explicitly reported; all configurations remain in
    # the frozen result and support JSON. Do not imply rerun optimization.
    selected=[(i,row) for i,row in enumerate(metrics['sensitivity_statistics']) if row['group']==2 and row['mode']=='two' and row['repair_range']==[600,1200]]
    for i,row in selected:
        contracts=[display(f'/sensitivity_statistics/{i}/fault_probability',row['fault_probability'],2,'percent'),
                   display(f'/sensitivity_statistics/{i}/mean',row['mean']),display(f'/sensitivity_statistics/{i}/sd',row['sd'])]
        prob=contracts[0]['display_value']
        sentence=f"组二双工序在故障概率 {prob}、修复范围 {row['repair_range'][0]} 至 {row['repair_range'][1]} 秒时，固定配置交付均值为 {fmt(row['mean'])} 件，样本标准差为 {fmt(row['sd'])} 件。"
        sens_claims.append(claim('SENSITIVITY-'+str(i),sentence,contracts));sens_rows.append([prob,fmt(row['mean']),fmt(row['sd'])])
    def table(headers,rows,lines):
        return '\n'.join(['|'+'|'.join(headers)+'|','|'+'|'.join(['---']*len(headers))+'|']+['|'+'|'.join(r)+'|' for r in rows]+lines)
    tables={
      'healthy':table(['参数组','正常单工序交付量','正常双工序交付量'],[[labels[i*2][:2],str(counts[f'g{i+1}_single_healthy']),str(counts[f'g{i+1}_two_healthy'])] for i in range(3)],[paragraphs['healthy']]),
      'fault':table(['配置','均值','标准差','最小','最大','均值近似区间'],stat_rows,stat_claims),
      'comparison':table(['配置','所选配置均值','对照配置均值','前缀样本均值'],compare_rows,compare_claims),
      'sensitivity':table(['故障概率','均值','标准差'],sens_rows,sens_claims),
    }
    # Plot only actual Result metrics. The source file and its dependency are
    # retained; current binding and readback do not imply semantic proof.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':10})
    (PROJECT/'paper/figures').mkdir(exist_ok=True)
    fig,ax=plt.subplots(figsize=(7,3.4),layout='constrained')
    x=list(range(3));width=.34
    ax.bar([v-width/2 for v in x],[counts[f'g{v+1}_single_healthy'] for v in x],width,label='正常单工序',color='#315b7b')
    ax.bar([v+width/2 for v in x],[counts[f'g{v+1}_two_healthy'] for v in x],width,label='正常双工序',color='#8a9a6a')
    ax.set_xticks(x,['组一','组二','组三']);ax.set_ylabel('交付工件数');ax.legend(frameon=False);ax.spines[['top','right']].set_visible(False)
    fig.savefig(PROJECT/'paper/figures/healthy.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,3.4),layout='constrained')
    ax.errorbar(range(6),[r['selected']['mean'] for r in metrics['fault_statistics']],yerr=[r['selected']['sd'] for r in metrics['fault_statistics']],fmt='o',capsize=4,color='#315b7b')
    ax.set_xticks(range(6),labels,rotation=15);ax.set_ylabel('均值与样本标准差');ax.spines[['top','right']].set_visible(False)
    fig.savefig(PROJECT/'paper/figures/fault.png',dpi=180);plt.close(fig)
    structures=[]
    for n,(key,value) in enumerate(tables.items(),1):
        path='paper/tables/'+key+'.md';write(PROJECT/path,value)
        oid=rt.register(rev(),'ArtifactRecord','paper.table.'+key,{'artifact_type':'table','path':path},dependencies=[ids['Q2']['result']],files=[path])['result']['object_id']
        structures.append({'kind':'table','number':n,'artifact_id':oid})
    for n,key in enumerate(['healthy','fault'],1):
        path='paper/figures/'+key+'.png'
        oid=rt.register(rev(),'ArtifactRecord','paper.figure.'+key,{'artifact_type':'figure','path':path},dependencies=[ids['Q2']['result']],files=[path])['result']['object_id']
        structures.append({'kind':'figure','number':n,'artifact_id':oid})
    reference_structure=[{'kind':'reference','number':n,'artifact_id':registry_id} for n in (1,2)]
    original_q1=cp['objects'][ids['Q1']['claim']]['payload']['claim']+' [[claim:'+ids['Q1']['claim']+']]'
    original_q2=cp['objects'][ids['Q2']['claim']]['payload']['claim']+' [[claim:'+ids['Q2']['claim']+']]'
    statement=render_cumcm_use_statement(validate_entries(rt.read()['compliance']['ai_usage'],competition='cumcm'),official=True).strip()
    q1=f'''# 智能车间 RGV 调度的历史复现与核验报告

历史复现与验证用途  非正式参赛稿

## 摘要

本报告围绕智能加工车间的 RGV 动态调度，复现单工序、双工序以及加工故障情形。模型把机床加工、车辆移动、上下料与清洗视为离散事件，采用有限候选派工策略与固定刀具配置。报告的主要目标是获得可独立回放的可行调度，并比较交付量及故障波动；所选方案的优势仅限于已枚举候选，不能解释为全局最优。

{original_q1}

结果表明，正常工况所选配置在不同参数组之间表现不同；正常工况选定的方案在故障下也可能弱于对照配置。故障统计和敏感性分析使用固定策略，不能作为重新优化后的性能。所有结果均来自本轮实际运行及独立验证，结论受随机故障模型、候选策略与实现假设限制。

关键词：动态调度；离散事件；独立回放；历史复现

# 1 问题重述

依据官方题面[1]，车间通过轨道上的 RGV 服务多台 CNC。需要给出动态调度方案，在单工序、双工序以及加工中可能发生故障的情形下，根据题给参数形成可执行方案与结果表。本报告遵循原题的任务划分，将不同工况视为任务内部需求，不把工况替换为新增子问。

[[source:problem_year]]

[[source:rules_year]]

规则年份仅说明文档验收采用的规则快照，与题目年份分开记录。本报告没有进入正式比赛提交状态，也未取得团队人工终审或赛事回执。

# 2 假设与符号

仿真中的加工、移动、上下料和清洗时间取自题给参数。车辆按顺序执行任务；同一机床只有满足上道工序与可用状态要求后才可服务。末工序完成并经过清洗的工件才计入班次交付量，班次边界外的清洗完成不计入本班次。

发生加工故障时，故障工件报废，机床在修复后重新进入可服务状态。故障时刻与修复时间采用实现中预先固定的抽样规则；这是待实验验证的建模假设，不表示真实车间分布已被确认。双工序刀具配置在正常工况搜索后固定，故障和敏感性实验不重新选择刀具配置。

记当前事件时刻为 t，车辆位置为 r，机床的下一次可服务时刻为 a，交付计数为 N。状态还记录工件所处工序、正在加工或等待的机床以及车辆已承诺动作。符号只是模型说明，不替代源程序中可执行的边界条件。

# 3 模型与求解

目标是在给定班次内使实际交付量尽可能大。每次派工先计算候选目标的车辆到达时刻，再结合机床完成时刻确定可服务时刻，并依次追加上下料、清洗等动作。若没有立即可行的目标，则推进至下一事件。对每个候选方案，统计满足加工先后次序、车辆不重叠和末工序完成条件的交付工件。

单工序比较循环、贪心与最早完成候选；双工序比较循环交替与贪心交替派工，在有限固定刀具分配中选择交付量较高的候选。平局按实现中确定的稳定顺序处理。候选集合有限，未使用完整状态空间最优性证书，也未证明搜索集合覆盖全部动态调度策略。

独立回放器从保存的命令序列重新检查移动、服务与加工时间、车辆动作互斥、工序衔接和实际交付。算法边界测试与独立回放是不同证据：前者验证若干典型边界，后者核对本次实际运行轨迹。二者都不能排除所有模型误设。
'''
    q2=f'''# 4 实验结果

{original_q2}

## 4.1 正常工况

表1给出正常工况的交付量，图1仅对这些数值作可视化。单工序与双工序的工艺约束不同，因此两列不能直接解释为同一生产任务的效率优劣。

[[table:1]]

{tables['healthy']}

[[figure:1]]

![正常工况交付量](paper/figures/healthy.png)

## 4.2 故障工况

表2列出固定配置下的故障样本统计，单位为件。区间为样本均值的正态近似区间，不能当作单次产出的保证区间；抽样分布、尾部行为和模型失配仍需另外检验。图2的误差线表示样本标准差，不表示均值区间。

[[table:2]]

{tables['fault']}

[[figure:2]]

![故障均值及样本标准差](paper/figures/fault.png)

## 4.3 对照与稳定性

表3比较所选配置、对照配置及同一序列前缀的样本均值。对照不是另一组独立随机实验，前缀统计也不能与全样本统计当作相互独立证据。组一双工序的对照均值高于所选配置，说明正常工况选优不能直接推广到故障工况。

[[table:3]]

{tables['comparison']}

## 4.4 敏感性分析

表4仅展示组二双工序、相同修复范围下的故障概率变化。其他配置的完整结果保存在支撑材料。实验固定正常工况选定策略，没有针对每个扰动重新优化，因而这里衡量的是固定策略对设定变化的反应。

[[table:4]]

{tables['sensitivity']}

# 5 独立验证与结果边界

{paragraphs['validation']}

外部检查器重新计算候选记录中的交付量、统计摘要和表格单元格；代表性命令轨迹另行回放。表格一致性证明的是导出数据与这次运行相符，不能独立证明模型对真实生产环境适用。由于调度器和检查器仍共享问题参数与部分定义，本报告保留建模假设风险，不把通过检查写成不存在任何错误。

# 6 结论与改进方向

已获得可回放、可导出并与论文数值绑定的有限候选调度结果。双工序配置选择会明显影响交付量，但正常工况的候选最优配置不能保证在随机故障下继续占优。后续可扩大动态派工与重配置策略、独立检验故障分布，并以新的冻结模型和重新运行结果评价改进；本稿没有把这些计划作为已完成工作。

# AI 工具使用声明

本报告使用的 AI 工具见参考文献[2]。以下采用规则快照中的声明句式，所述内容只对应本次历史复现过程，不表示实际参加该届竞赛。

{statement}

AI 使用过程、采用范围和人工核验状态见支撑材料。人工终审尚未完成。

# 参考文献

[[reference:1]]

[[reference:2]]

# 附录

支撑材料文件清单与完整源程序如下。匿名运行说明给出实际数据入口、依赖和执行方式；结果文件是已验证运行输出的便于阅读副本，完整运行来源仍保存在项目证据目录。
'''
    # Every submitted path is present in the source before rendering. The
    # executable content itself is derived through source_code supplements.
    support_paths=['driver.py','rgv_simulator.py','test_rgv.py','checker.py','verify_schedule.py','assets/official_parameters.json',
      'run_context.json','paper/运行说明.md','paper/AI工具使用详情.pdf','results/Q2/experiment_summary.json','results/Q2/healthy_comparison.csv']
    # The complete list is emitted later from bound file_list supplements;
    # filenames are not experimental numeric claims.
    q1 += '\n\n每单位班次时长的交付效率定义如下，其中 E 为交付率，N 为实际交付量，T 为班次时长。此处为原生分式的来源回读验收，不改变调度目标。\n\n$$E=\\frac{N}{T}$$\n'
    write(PROJECT/'paper/introduction.md',q1);write(PROJECT/'paper/results.md',q2)
    # Cross-reference declarations are scoped to each Section. Their derived
    # bibliography blocks occur exactly once per section, so all references
    # are declared in the results section; the problem citation is moved there.
    q1=q1.replace('官方题面[1]','官方题面')
    q2=q2.replace('# 4 实验结果','# 4 实验结果\n\n实验参数与任务定义依据官方题面[1]。')
    write(PROJECT/'paper/introduction.md',q1);write(PROJECT/'paper/results.md',q2)
    sections=[]
    sections.append(delivery.section(rev(),'paper.Q1','paper/introduction.md',[ids['Q1']['claim']],source_bindings=[
      {'id':'problem_year','kind':'year','source_id':lock,'source_path':'/problem_year'},
      {'id':'rules_year','kind':'year','source_id':lock,'source_path':'/rules_year'}],structure=[])['result']['section_id'])
    sections.append(delivery.section(rev(),'paper.Q2','paper/results.md',claim_ids,source_bindings=[],structure=structures+reference_structure)['result']['section_id'])
    cp=rt.read()['copilot'];supplements=[]
    for path in ['driver.py','rgv_simulator.py','test_rgv.py','checker.py','verify_schedule.py']:
        owner=next(obj['id'] for obj in cp['objects'].values() if obj['kind'] in {'CodeManifest','ValidationPlan'} and cp['current'].get(obj['key'])==obj['id'] and any(f['path']==path for f in obj['files']))
        supplements.append({'kind':'source_code','source_id':owner,'path':path})
    contract={'version':'0.1','sections':sections,'supplements':supplements}
    write(PROJECT/'paper/source_contract.json',contract)
    write(PROJECT/'paper/chain_plan.json',{'sections':sections,'claims':[ids['Q1']['claim']]+claim_ids,'support_paths':support_paths,
      'paper_source':'paper/source_contract.json','citation_registry':'paper/reference_registry.json','benchmark_ids':ids,'created_at':now})
    # Reproduce the exact frozen Q2 driver context without embedding personal
    # paths or runtime receipt environment into the contest support archive.
    shutil.copy2(PROJECT/ids['Q2']['directory']/'run_context.json',PROJECT/'run_context.json')
    write(PROJECT/'paper/运行说明.md','''# 历史调度复现运行说明

本材料用于历史验证，不是正式参赛提交。需要 Python 和 xlrd、xlwt；算法模块仅用标准库。

在解压目录执行：

python driver.py

入口读取冻结的模型、参数与数据合同，真实重新计算全部实验。生成结果将写入 results，不应覆盖要保留的运行证据；请在新的解压副本内执行。独立轨迹校验由 verify_schedule.py 实现，原算法边界测试可运行 python test_rgv.py。checker.py 是 Copilot 的预声明检查器，其 --run 参数需要完整 Runtime RunRecord，不应以手工伪造的回执代替。

完整复现实验包括候选搜索、故障与敏感性统计，可能需要数分钟。本包结果表及统计是本次执行的读取副本；完整审计项目提供版本、对象与输入输出 hash。
''')
    write(PROJECT/'paper/AI工具使用详情.md',render_cumcm_markdown(validate_entries(rt.read()['compliance']['ai_usage'],competition='cumcm'),rt.read()))
    print(json.dumps({'sections':sections,'claims':len(claim_ids)+1,'contract':'paper/source_contract.json'},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
