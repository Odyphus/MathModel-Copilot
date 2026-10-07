'use strict';
(() => {
  async function read(url) {
    let response;
    try {
      response = await fetch(url, {method:'GET', credentials:'omit', cache:'no-store',
        headers:{'X-Copilot-Read':'1'}, signal:AbortSignal.timeout(20000)});
    } catch {
      const error = new Error('未能连接本地服务或读取超时。确认服务仍在运行，检查工作区后重试。');
      error.name='OfflineError'; throw error;
    }
    let body;
    try { body = await response.json(); } catch { throw new Error('本地服务没有返回可识别的读取结果。'); }
    if (!response.ok || body.ok !== true) throw new Error(body.message || '本次读取未成功，请检查项目后再试。');
    return body.result;
  }
  window.CopilotData = {
    preview:false,
    load:() => read('/api/snapshot'),
    tutorial:topic => read('/api/tutorial' + (topic ? '?topic=' + encodeURIComponent(topic) : '')),
    recap:() => read('/api/recap'),
    readFile:(view, path) => read('/api/file?' + new URLSearchParams({path,
      snapshot:view.snapshot_id, revision:String(view.revision), authority:view.authority_file_sha256,
      observation:view.file_observation_hash}))
  };
})();
