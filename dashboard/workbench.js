'use strict';
// A local reading cursor, never a second project store or a verification gate.
// This module is pure: it does not access storage, the DOM, HTTP, or business writers.
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CopilotWorkbench = api;
})(typeof window === 'undefined' ? globalThis : window, function () {
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const safeId = value => typeof value === 'string' && value.length > 0 && value.length <= 512 &&
    !/[\x00-\x1f\x7f<>]/.test(value) && !['__proto__', 'prototype', 'constructor'].includes(value);
  const sha = value => typeof value === 'string' && /^[a-f\d]{64}$/i.test(value);
  const status = value => typeof value === 'string' && /^[a-z][a-z_]{0,47}$/.test(value);
  const fields = (value, expected) => record(value) && Object.keys(value).length === expected.length && expected.every(key => own(value, key));
  const timestamp = value => typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value.slice(0, 10) + 'T00:00:00Z').toISOString().startsWith(value.slice(0, 10));
  const hasErrors = value => Array.isArray(value) ? value.length > 0 : record(value) && Object.keys(value).length > 0;
  const isStale = value => value.effective_status === 'stale' || value.status === 'stale' || hasErrors(value.current_errors);
  const shownStatus = value => isStale(value) ? 'stale' : status(value.effective_status) ? value.effective_status : status(value.status) ? value.status : 'unknown';

  function decisionItems(view) {
    const rows = view?.status?.interpretations;
    if (!Array.isArray(rows)) return [];
    const severity = {critical: 0, high: 1, medium: 2, low: 3};
    return rows.filter(row => record(row) && safeId(row.object_id) && row.is_current !== false &&
      view.objects?.[row.object_id]?.is_current !== false &&
      ['AmbiguityEntry', 'AssumptionEntry'].includes(row.kind) &&
      (hasErrors(row.current_errors) || row.kind === 'AmbiguityEntry' && row.status === 'open' ||
        row.kind === 'AssumptionEntry' && row.status === 'proposed'))
      .sort((a, b) => (severity[a.payload?.severity] ?? 4) - (severity[b.payload?.severity] ?? 4));
  }

  function canonical(value) {
    if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
    if (record(value)) return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
    return JSON.stringify(value) ?? 'null';
  }

  const interpretationKinds = ['AmbiguityEntry', 'AssumptionEntry'];
  const omit = (value, keys) => Object.fromEntries(Object.entries(value || {}).filter(([key]) => !keys.includes(key)));
  function currentInterpretations(view) {
    return (view?.status?.interpretations || []).filter(row => record(row) && interpretationKinds.includes(row.kind) &&
      row.is_current !== false && view.objects?.[row.object_id]?.is_current !== false);
  }
  function interpretationPayload(value) {
    // Only identity, question bindings and event bookkeeping are excluded.
    // Unknown fields, exact wording/order, choices and evidence remain in the key.
    const payload = omit(value, ['question', 'ambiguity_id', 'assumption_id', 'requirement_ids',
      'linked_requirement_ids', 'linked_ambiguity_ids', 'timestamp', 'stable_id', 'semantic_hash', 'record_hash', 'parent_record_hash']);
    if (record(payload.review)) payload.review = omit(payload.review, ['at']);
    return payload;
  }
  function interpretationContent(row, view) {
    const object = view.objects?.[row.object_id];
    return {row: omit(row, ['object_id', 'question', 'payload']), payload: interpretationPayload(row.payload),
      object: object ? {kind: object.kind, status: object.status, effective_status: object.effective_status,
        is_current: object.is_current, current_errors: object.current_errors, files: object.files,
        payload: interpretationPayload(object.payload)} : null};
  }
  function interpretationKey(row, view, rows) {
    const object = view.objects?.[row.object_id], p = row.payload;
    if (!object || object.is_current === false || !record(p) || !row.question ||
      row.kind === 'AmbiguityEntry' && (!Array.isArray(p.interpretations) || !p.interpretations.length) ||
      row.kind === 'AssumptionEntry' && (typeof p.statement !== 'string' || !p.statement.trim())) return null;
    const linked = (item, id) => rows.filter(other => other.kind === 'AmbiguityEntry' &&
      other.question === item.question && other.payload?.ambiguity_id === id);
    const relations = item => ({
      ambiguities: (item.payload?.linked_ambiguity_ids || []).map(id => {
        const matches = linked(item, id);
        return matches.length === 1 && view.objects?.[matches[0].object_id]?.is_current !== false && view.objects?.[matches[0].object_id]
          ? interpretationContent(matches[0], view) : {unresolved: id, object_id: item.object_id};
      }),
      dependencies: (view.objects?.[item.object_id]?.dependencies || []).map(id => {
        const match = rows.find(other => other.object_id === id && other.kind === 'AmbiguityEntry' &&
          (item.payload?.linked_ambiguity_ids || []).includes(other.payload?.ambiguity_id));
        return match && view.objects?.[id]?.is_current !== false && view.objects?.[id]
          ? interpretationContent(match, view) : id;
      })
    });
    const assumptions = row.kind === 'AmbiguityEntry' ? rows.filter(other => other.kind === 'AssumptionEntry' &&
      other.question === row.question && (other.payload?.linked_ambiguity_ids || []).includes(p.ambiguity_id))
      .map(other => ({content: interpretationContent(other, view), relations: relations(other)})) : [];
    return canonical({content: interpretationContent(row, view), relations: relations(row), assumptions});
  }
  function interpretationGroups(view, items) {
    const groups = [], rows = currentInterpretations(view);
    for (const item of items) {
      const key = interpretationKey(item, view, rows);
      // This combines repeated descriptions across questions, never counts,
      // same-question records, missing records or the underlying domain objects.
      let group = key && groups.find(group => group.key === key && !group.questions.includes(item.question));
      if (!group) {group = {key, items: [], questions: []}; groups.push(group);}
      group.items.push(item); group.questions.push(item.question);
    }
    return groups.map(({items, questions}) => ({items, questions}));
  }
  function blockerItems(view, texts, aggregate = false) {
    const rows = currentInterpretations(view), result = [];
    const patterns = [
      ['AmbiguityEntry', 'ambiguity_id', '题意歧义待解决或带条件假设', '题意仍待明确或带条件推进'],
      ['AssumptionEntry', 'assumption_id', '假设尚未明确采纳或拒绝', '假设仍待判断是否采用'],
      ['AssumptionEntry', 'assumption_id', '已接受假设仍待实际核验', '已采用假设，待实际核验']
    ];
    for (const text of new Set(texts)) {
      let matches = [], message = '';
      for (const [kind, field, raw, label] of patterns) {
        const found = rows.filter(row => row.kind === kind && view.objects?.[row.object_id] &&
          text === `${row.question} ${raw}：${row.payload?.[field]}`);
        if (found.length) {matches = found; message = label; break;}
      }
      if (matches.length !== 1) {result.push({message: text, items: [], originals: [text]}); continue;}
      const item = matches[0];
      const group = aggregate && result.find(entry => entry.message === message && entry.items.length &&
        interpretationGroups(view, [...entry.items, item]).length === 1);
      if (group) {group.items.push(item); group.originals.push(text);}
      else result.push({message, items: [item], originals: [text]});
    }
    return result;
  }

  function marker(value) {
    // Two compact non-cryptographic checksums only detect reading changes.
    // Authority/file SHA256 values below remain independent change indicators;
    // neither this checksum nor any saved status can establish current validity.
    const text = canonical(value);
    let a = 0x811c9dc5, b = 0x9e3779b9;
    for (let i = 0; i < text.length; i++) {
      const c = text.charCodeAt(i);
      a = Math.imul(a ^ c, 0x01000193);
      b = Math.imul(b ^ c, 0x85ebca6b);
    }
    return (a >>> 0).toString(16).padStart(8, '0') + (b >>> 0).toString(16).padStart(8, '0');
  }

  function metadata(view) {
    return record(view) && safeId(view.project_id) && Number.isSafeInteger(view.revision) && view.revision >= 0 &&
      sha(view.state_hash) && sha(view.file_observation_hash) && timestamp(view.checked_at);
  }

  function makeVisit(view) {
    if (!metadata(view)) return null;
    const objects = {}, tasks = {}, requirements = {};
    for (const [id, obj] of Object.entries(view.objects || {})) {
      if (!safeId(id) || !record(obj) || obj.is_current !== true) continue;
      const observed = (Array.isArray(obj.files) ? obj.files : []).map(file => view.observed_files?.[file.path] ?? null);
      objects[id] = {status: shownStatus(obj), hash: marker([obj, observed])};
    }
    for (const [id, task] of Object.entries(view.tasks || {})) {
      if (safeId(id) && record(task)) tasks[id] = {status: shownStatus(task), hash: marker(task)};
    }
    // Coverage status comes only from the checked projection, not a guessed
    // Requirement payload status or from the last time this browser was opened.
    for (const row of view.status?.requirements?.rows || []) {
      if (!record(row) || !safeId(row.id) || view.requirements?.[row.id]?.active === false) continue;
      requirements[row.id] = {status: shownStatus(row), hash: marker([row, view.requirements?.[row.id] ?? null])};
    }
    return {version: 1, project_id: view.project_id, revision: view.revision, state_hash: view.state_hash,
      file_observation_hash: view.file_observation_hash, checked_at: view.checked_at, objects, tasks, requirements};
  }

  function validMarks(map) {
    return record(map) && Object.entries(map).every(([id, entry]) => safeId(id) &&
      fields(entry, ['status', 'hash']) && status(entry.status) && typeof entry.hash === 'string' && /^[a-f\d]{16}$/.test(entry.hash));
  }

  function validVisit(visit, view) {
    return metadata(view) && fields(visit, ['version', 'project_id', 'revision', 'state_hash', 'file_observation_hash',
      'checked_at', 'objects', 'tasks', 'requirements']) && visit.version === 1 && metadata(visit) &&
      visit.project_id === view.project_id && visit.revision <= view.revision &&
      Date.parse(visit.checked_at) <= Date.parse(view.checked_at) &&
      validMarks(visit.objects) && validMarks(visit.tasks) && validMarks(visit.requirements);
  }

  function parseVisit(raw, view) {
    if (typeof raw !== 'string' || raw.length > 4000000) return null;
    try {
      const visit = JSON.parse(raw);
      return validVisit(visit, view) ? visit : null;
    } catch { return null; }
  }

  function changeItems(view, visit) {
    const now = makeVisit(view);
    if (!now || !validVisit(visit, view)) return {reset: true, items: [], otherChanges: false};
    const items = [];
    let removed = false;
    for (const group of ['objects', 'tasks', 'requirements']) {
      for (const id of Object.keys(visit[group])) if (!own(now[group], id)) removed = true;
      for (const [id, entry] of Object.entries(now[group])) {
        const old = visit[group][id];
        if (old && old.status === entry.status && old.hash === entry.hash) continue;
        if (group === 'objects') {
          const obj = view.objects[id];
          items.push({kind: isStale(obj) ? 'stale' : obj.kind === 'ResultRecord' ? 'result' : obj.kind === 'ModelSpec' ? 'model' : 'other', object_id: id});
        } else if (group === 'tasks') {
          items.push({kind: isStale(view.tasks[id]) ? 'stale' : 'task', task_id: id});
        } else {
          items.push({kind: 'requirement', requirement_id: id});
        }
      }
    }
    // A changed authority/file observation without an item-level difference can
    // be a withdrawal, a journal-only edit, or a same-revision file drift.
    // Keep a generic notice instead of falsely saying "nothing changed".
    const observationChanged = now.revision !== visit.revision || now.state_hash !== visit.state_hash ||
      now.file_observation_hash !== visit.file_observation_hash;
    return {reset: false, items, otherChanges: removed || observationChanged && items.length === 0};
  }

  return {decisionItems, interpretationGroups, blockerItems, makeVisit, parseVisit, changeItems};
});
