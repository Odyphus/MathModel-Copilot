"""Timely selected context, live resumption and conditional personal lessons."""
from __future__ import annotations

import copy
import hashlib
import html
import json
from pathlib import Path
import re
import uuid

from copilot_experience import ExperienceStorage, text, ID, _safe_component
from copilot_store import ConflictError, IntegrityError, digest, file_lock, utc_now


def observation(workspace):
    """Always read the authority AND files, even at the same revision."""
    from copilot_summary import report
    try:
        value = report(workspace)
        fingerprint = digest({k:value[k] for k in ('project_id','revision','authority_file_sha256',
                                                   'file_observation_hash','report_facts')})
        return {'available':True,'fingerprint':fingerprint,'report':value}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Missing/untrusted authority remains visibly unavailable, not a report
        # with zero requirements or a cached PASS substituted for current facts.
        return {'available':False,'observed_at':utc_now(), 'error_kind':type(exc).__name__,
                'message':str(exc),'fingerprint':digest([type(exc).__name__, str(exc)])}


def _allowed(store, rec):
    settings = store.settings()
    effective = settings['project_overrides'].get(store.binding, settings['recap_default'])
    if rec.get('recording_scope') == 'once':
        if settings['settings_revision'] > rec['consent_settings_revision'] and effective == 'off':
            raise ValueError('保存设置已关闭，未继续记录；如需本次保存请重新明确请求')
    elif effective != 'on':
        raise ValueError('本项目尚未开启或已关闭过程记录，未自动保存')


def _get(store, rid):
    rec = store.read('experiences', rid)
    if rec is None or rec.get('kind') != 'experience':
        raise ValueError('未找到本项目的体验记录')
    return rec


def start(store, goal, request_id, *, save_once=False, user_request=None):
    text(goal, '本次目标', 2000)
    text(request_id, '本次工作标识', 200)
    settings = store.settings()
    if save_once:
        text(user_request, '本次保存请求', 2000)
    elif not store.recording_enabled():
        raise ValueError('尚未同意自动记录；请先展示范围并设置，或使用明确的单次保存请求')
    rid = 'EXP-' + digest([store.binding, request_id])[:24]
    prior = store.read('experiences', rid)
    if prior:
        if prior['goal'] != goal or prior['request_id'] != request_id:
            raise ConflictError('同一本次工作标识已用于不同目标')
        return prior
    value = {'kind':'experience','id':rid,'request_id':request_id,'goal':goal,'state':'active',
             'created_at':utc_now(),'recording_scope':'once' if save_once else 'project',
             'consent_settings_revision':settings['settings_revision'],
             'consent_source':user_request if save_once else 'explicit settings',
             'initial_observation':observation(store.workspace), 'events':[], 'recaps':[]}
    try:
        return store.write('experiences', rid, value)
    except ConflictError:
        prior = store.read('experiences', rid)
        if prior and prior['goal'] == goal and prior['request_id'] == request_id:
            return prior
        raise


def record_event(store, rid, revision, payload):
    rec = _get(store, rid)
    _allowed(store, rec)
    allowed = {'event_id','kind','text','source_kind','source_ref','source_file','start_line','end_line'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('过程输入含未知字段，不能提供程序事实或完成度')
    event_id = text(payload.get('event_id'), '事件标识', 120)
    kind = payload.get('kind')
    if kind not in {'decision','correction','failure','recovery','handoff','note'}:
        raise ValueError('过程类型无效')
    content = text(payload.get('text'), '必要过程片段', 8000)
    source_kind = payload.get('source_kind')
    if source_kind not in {'artifact_excerpt','user_report','agent_summary'}:
        raise ValueError('来源须区分 artifact_excerpt、user_report、agent_summary')
    source = {'kind':source_kind, 'reference':text(payload.get('source_ref',''), '来源说明', 1000, empty=True),
              'scope':'用户提供的报告' if source_kind == 'user_report' else 'AI转述，不能当作原话'}
    if source_kind == 'artifact_excerpt':
        from copilot_runtime import safe_path
        relative = text(payload.get('source_file'), '选定来源文件', 400)
        p = safe_path(store.workspace, relative)
        if p.stat().st_size > 1024*1024:
            raise ValueError('来源文件过大，请先由用户选取相关片段')
        raw = p.read_bytes()
        lines = raw.decode('utf-8').splitlines()
        a,b = payload.get('start_line'),payload.get('end_line')
        if type(a) is not int or type(b) is not int or not 1 <= a <= b <= len(lines) or b-a > 100:
            raise ValueError('选定片段行号无效或范围过大')
        if '\n'.join(lines[a-1:b]) != content:
            raise ValueError('原文与实际文件片段不一致，不能登记为原文')
        source.update(file=relative, sha256=hashlib.sha256(raw).hexdigest(), start_line=a, end_line=b,
                      scope='所选本地文件的逐字片段；文件来源身份未由程序认证')
    elif any(k in payload for k in ('source_file','start_line','end_line')):
        raise ValueError('只有逐字文件片段可以绑定文件和行号')
    intent = digest(payload)
    existing = next((x for x in rec['events'] if x['event_id'] == event_id), None)
    if existing:
        if existing['intent'] != intent or existing['source'] != source:
            raise ConflictError('同一事件标识的内容或来源已变化，请使用新的事件')
        return rec
    if rec['state'] != 'active':
        raise ValueError('本次已收尾，请为新的工作开启新体验记录')
    if len(rec['events']) >= 200:
        raise ValueError('本段已达200个关键片段，停止新增并明确覆盖范围；不要归档全部聊天')
    rec['events'].append({'event_id':event_id,'kind':kind,'text':content,'source':source,
                          'intent':intent,'recorded_at':utc_now()})
    return store.write('experiences', rid, rec, revision)


def _analysis(payload):
    if not isinstance(payload, dict) or set(payload) - {'summary','next_steps','missing_context'}:
        raise ValueError('分析输入只能包含 summary、next_steps、missing_context；不能填写已核验事实')
    value = {'summary':text(payload.get('summary',''), '分析', 6000, empty=True)}
    for field in ('next_steps','missing_context'):
        items=payload.get(field,[])
        if not isinstance(items,list) or len(items)>20:
            raise ValueError(field+' 必须为不超过20项的列表')
        value[field]=[text(x,field,1000) for x in items]
    return value


def _esc(value):
    return html.escape(str(value)).replace('`','\\`').replace('|','\\|').replace('#','\\#')


def markdown(rec, item):
    rows=['# 本次复盘','', '本次目标：'+_esc(rec['goal']), '观察时间：'+item['created_at'],
          '', '## 本次实际记录', '',
          '覆盖范围：仅本次已保存的选定片段与实际项目观察；不代表全部宿主对话。']
    current=item['observation']
    if current['available']:
        facts=current['report']['report_facts']
        reqs=facts['requirements']
        rows += [f"- 当前已核验要求：{reqs['verified']} / {reqs['total']}。",
                 f"- 当前可用的已核验结果：{len(facts['results'])} 份。",
                 '- 提交材料检查：'+('当前检查通过，仍需实际提交与人工事项。' if facts['submission'].get('ready') else '尚未满足。')]
        for result in facts['results']:
            rows.append('- '+_esc(result['question'])+'：'+_esc(result.get('scope') or '适用范围未登记'))
    else:
        rows += ['当前项目事实无法核对，不能由本复盘推定完成或核验通过。',
                 '原因：'+_esc(current['error_kind'])+'；'+_esc(current['message'])]
    rows += ['', '## 关键过程与来源','']
    for event in rec['events']:
        rows += ['- '+_esc(event['text']), '  来源：'+_esc(event['source']['scope'])]
    if not rec['events']:
        rows.append('没有取得已保存的关键交互；未补写或推测原话。')
    rows += ['', '## AI 整理与待判断事项','',_esc(item['analysis']['summary'] or '本次未附加 AI 分析。'),
             '', '## 下次从哪里继续','']
    rows += ['- '+_esc(x) for x in item['analysis']['next_steps']] or ['读取当前项目状态后确定下一步。']
    rows += ['', '## 缺失与边界','', '- 部分过程未取得；仅覆盖保存的材料，不能证明全部交流。']
    rows += ['- '+_esc(x) for x in item['analysis']['missing_context']]
    rows += ['', '历史复盘不替代当前权威状态；再次进入时需要重查文件和有效结果。','']
    return '\n'.join(rows)


def close(store, rid, revision, reason, analysis=None):
    if reason not in {'goal_finished','handoff','stopped','failed','manual','recovered'}:
        raise ValueError('收尾原因无效')
    rec=_get(store,rid)
    _allowed(store,rec)
    info=_analysis(analysis or {})
    current=observation(store.workspace)
    key=digest({'observation':current['fingerprint'],'events':rec['events'],'analysis':info,'reason':reason})
    if rec['recaps'] and rec['recaps'][-1]['content_key']==key:
        return {'record':rec,'recap':rec['recaps'][-1],'reused':True,
                'saved_to':_save_markdown(store, rid, rec['recaps'][-1])}
    if len(rec['recaps'])>=50:
        raise ValueError('历史复盘版本过多，请为新的工作开启新体验')
    item={'version':len(rec['recaps'])+1,'content_key':key,'created_at':utc_now(),
          'reason':reason,'observation':current,'analysis':info,'context_coverage':'partial'}
    item['markdown']=markdown(rec,item)
    rec['recaps'].append(item)
    rec['state']='closed'
    saved=store.write('experiences',rid,rec,revision)
    # Save the record first. If the derivative fails, retry repairs that exact
    # version instead of inventing a second recap or reporting false success.
    return {'record':saved,'recap':saved['recaps'][-1],'reused':False,
            'saved_to':_save_markdown(store, rid, saved['recaps'][-1])}


def _save_markdown(store, rid, item):
    path=store.path('recaps',f"{rid}-v{item['version']}.md")
    # Same lock order as forget: a concurrent deletion cannot resurrect a view.
    with file_lock(store.path('experiences',rid+'.lock')):
        current=store.read('experiences',rid)
        if not current or not any(x==item for x in current.get('recaps',[])):
            raise ConflictError('复盘已删除或版本已变化，未重建文档')
        with file_lock(store.path('recaps',rid+'.lock')):
            if not path.exists():
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('x',encoding='utf-8',newline='\n') as out:
                    out.write(item['markdown'])
                    out.flush()
                    import os
                    os.fsync(out.fileno())
            if path.read_text(encoding='utf-8') != item['markdown']:
                raise IntegrityError('复盘文档与保存版本不符；保留现有文档，未覆盖或宣称保存成功')
    return str(path)


def _tags(tags):
    if not isinstance(tags,list) or len(tags)>12:
        raise ValueError('经验标签最多12项')
    if any(not isinstance(t,str) or not re.fullmatch(r'[\w\-]{1,40}',t) for t in tags):
        raise ValueError('标签只允许简短名称，不接受路径或指令')
    return sorted(set(t.casefold() for t in tags))


def save_lesson(store, payload, user_request):
    text(user_request,'选定经验的明确请求',2000)
    if not isinstance(payload,dict) or set(payload)-{'text','conditions','tags','source_experience','source_kind','reusable'}:
        raise ValueError('经验字段无效')
    lesson={'kind':'lesson','id':'LESSON-'+uuid.uuid4().hex[:24],
            'text':text(payload.get('text'),'经验',3000),
            'conditions':text(payload.get('conditions'),'适用条件',2000),
            'tags':_tags(payload.get('tags',[])),'state':'selected','created_at':utc_now(),
            'user_request':user_request,'reusable':payload.get('reusable',False),
            'source_kind':payload.get('source_kind','user_suggestion')}
    if type(lesson['reusable']) is not bool or lesson['source_kind'] not in {'experience','user_suggestion'}:
        raise ValueError('经验复用范围或来源无效')
    if lesson['source_kind']=='experience':
        rec=_get(store,payload.get('source_experience'))
        if not rec['recaps']:
            raise ValueError('来源体验尚无复盘')
        lesson['source_experience']=rec['id']
        lesson['source_key']=rec['recaps'][-1]['content_key']
        lesson['source_workspace']=str(store.workspace)
        lesson['source_fingerprint']=rec['recaps'][-1]['observation']['fingerprint']
    elif payload.get('source_experience'):
        raise ValueError('用户建议不能伪造已验证的体验来源')
    return store.write('lessons',lesson['id'],lesson)


def withdraw_lesson(store,rid,revision):
    value=store.read('lessons',rid)
    if not value or value.get('kind')!='lesson':
        raise ValueError('未找到本项目创建的经验')
    value['state']='withdrawn'
    return store.write('lessons',rid,value,revision)


def edit_lesson(store,rid,revision,patch,user_request):
    text(user_request,'修改经验的明确请求',2000)
    value=store.read('lessons',rid)
    if not value or value.get('kind')!='lesson':
        raise ValueError('未找到本项目创建的经验')
    if not isinstance(patch,dict) or not patch or set(patch)-{'text','conditions','tags','reusable'}:
        raise ValueError('经验修改只接受 text、conditions、tags、reusable，不能改写来源')
    if 'text' in patch: value['text']=text(patch['text'],'经验',3000)
    if 'conditions' in patch: value['conditions']=text(patch['conditions'],'适用条件',2000)
    if 'tags' in patch: value['tags']=_tags(patch['tags'])
    if 'reusable' in patch:
        if type(patch['reusable']) is not bool: raise ValueError('reusable 必须为布尔值')
        value['reusable']=patch['reusable']
    value.update(user_request=user_request,updated_at=utc_now())
    return store.write('lessons',rid,value,revision)


def match_lessons(store,tags):
    if not store.settings()['experience_reuse']:
        return {'enabled':False,'selected':[],'excluded':[],'notice':'尚未开启跨项目经验读取'}
    tags=_tags(tags)
    selected=[];excluded=[]
    for item in store.list('lessons',cross_project=True):
        if item.get('state')!='selected' or not item.get('reusable'):
            continue
        common=sorted(set(tags)&set(item.get('tags',[])))
        if not common:
            continue
        if item['source_kind']=='experience':
            # The location is a private reference for a selected lesson, not a
            # source of commands; stale/missing history cannot be recommended.
            try:
                origin=ExperienceStorage(item['source_workspace'],store.root)
                src=origin.read('experiences',item['source_experience'])
            except (ValueError,OSError,KeyError,TypeError):
                excluded.append({'id':item['id'],'reason':'来源复盘无法安全读取，需要重新判断'});continue
            if (not src or not any(x['content_key']==item['source_key'] for x in src.get('recaps',[]))):
                excluded.append({'id':item['id'],'reason':'来源复盘已撤回或缺失'});continue
            now=observation(origin.workspace)
            if not now['available'] or now['fingerprint']!=item['source_fingerprint']:
                excluded.append({'id':item['id'],'reason':'来源项目已变化或无法核对，需要重新判断'});continue
        selected.append({'id':item['id'],'text':item['text'],'conditions':item['conditions'],
                         'source_kind':item['source_kind'],'matched_tags':common,
                         'reason':'标签相关，仅供对照适用条件；不自动采用为本题假设或结论'})
    return {'enabled':True,'selected':selected[:5],'excluded':excluded,
            'truncated':len(selected)>5,'notice':'当前题意与明确指令优先，经验不是科学核验'}


def resume(store,tags=None):
    records=store.list('experiences')
    records.sort(key=lambda x:x.get('created_at',''),reverse=True)
    closed=max((x for x in records if x.get('recaps')),
               key=lambda x:x['recaps'][-1]['created_at'],default=None)
    active=[{'id':x['id'],'goal':x['goal'],'record_revision':x['record_revision'],
             'saved_events':len(x['events'])} for x in records if x.get('state')=='active']
    current=observation(store.workspace)
    old=closed['recaps'][-1] if closed else None
    return {'current':current,'previous':{'goal':closed['goal'],'recap':old} if closed else None,
            'changed_since_recap':old['observation']['fingerprint']!=current['fingerprint'] if old else None,
            'unfinished_experiences':active,'preferences':store.settings()['preferences'],
            'lessons':match_lessons(store,tags or []),
            'notice':'先以 current 判断有效结果；previous 仅解释历史取舍。未完成记录不代表后台仍在运行。'}


def overview(workspace,user_data=None):
    try:
        store=ExperienceStorage(workspace,user_data)
        records=store.list('experiences')
        recaps=[(x,x['recaps'][-1]) for x in records if x.get('recaps')]
        if not recaps:
            return {'enabled':True,'recap':None,'notice':'尚未保存本项目复盘；可向当前 AI 请求整理。'}
        rec,item=max(recaps,key=lambda pair:pair[1]['created_at'])
        return {'enabled':True,'recap':{'title':'本次复盘','observed_at':item['created_at'],
                'markdown':item['markdown'],'partial':True},
                'notice':'这是历史复盘；当前有效结果请以工作台最新观察为准。'}
    except (ValueError,OSError,KeyError,TypeError):
        return {'enabled':False,'recap':None,'notice':'个人复盘暂时无法读取；请在当前 AI 中检查个人目录与设置。'}


def export_recap(store,rid,output):
    rec=_get(store,rid)
    if not rec['recaps']:
        raise ValueError('本次尚无已保存复盘')
    p=Path(output).absolute()
    for part in p.parts[1:]:
        _safe_component(part)
    if p.suffix.lower()!='.md' or p.exists():
        raise ValueError('导出需要一个尚不存在的 .md 文件，不覆盖作者文档')
    for ancestor in (p,*p.parents):
        if ancestor.is_symlink() or (hasattr(ancestor,'is_junction') and ancestor.is_junction()):
            raise ValueError('导出路径不能经过链接')
    # Explicit export may be shared, but can never write authority/private internals.
    if any(part.casefold() in {'state','.copilot','.git'} for part in p.parts):
        raise ValueError('不能导出到状态或运行目录')
    try:
        p.relative_to(store.root)
    except ValueError:
        pass
    else:
        raise ValueError('导出须另选普通文件，不能覆盖个人记录存储结构')
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8',newline='\n') as out:
        out.write(rec['recaps'][-1]['markdown'])
    if p.read_text(encoding='utf-8')!=rec['recaps'][-1]['markdown']:
        raise IntegrityError('导出未通过回读')
    return {'saved_to':str(p),'notice':'这是明确导出的个人材料；未自动上传或发送给队友'}


def forget(store,collection,rid,revision):
    if collection not in {'experiences','lessons'}:
        raise ValueError('只允许删除明确选定的本地复盘或经验')
    with file_lock(store.path(collection,rid+'.lock')):
        value=store.read(collection,rid)
        if not value or value['record_revision']!=revision:
            raise ConflictError('记录已变化或不存在；未删除')
        if collection=='experiences':
            with file_lock(store.path('recaps',rid+'.lock')):
                paths=[store.path('recaps',f"{rid}-v{x['version']}.md") for x in value.get('recaps',[])]
                for path in paths:
                    if path.exists():
                        path.unlink()
        store.path(collection,rid+'.json').unlink()
    return {'deleted':rid,'collection':collection,'remote_deleted':False}
