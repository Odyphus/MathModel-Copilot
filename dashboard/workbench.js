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
    const severity = {high: 0, medium: 1, low: 2};
    return rows.filter(row => record(row) && safeId(row.object_id) && row.is_current !== false &&
      view.objects?.[row.object_id]?.is_current !== false &&
      ['AmbiguityEntry', 'AssumptionEntry'].includes(row.kind) &&
      (hasErrors(row.current_errors) || row.kind === 'AmbiguityEntry' && row.status === 'open' ||
        row.kind === 'AssumptionEntry' && row.status === 'proposed'))
      .sort((a, b) => (severity[a.payload?.severity] ?? 3) - (severity[b.payload?.severity] ?? 3));
  }

  function canonical(value) {
    if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
    if (record(value)) return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
    return JSON.stringify(value) ?? 'null';
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

  return {decisionItems, makeVisit, parseVisit, changeItems};
});
