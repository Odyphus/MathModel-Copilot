"""Local workbench, public teaching, project-bound recap and optional opinions."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from copilot_store import ConflictError, IntegrityError
from copilot_view import snapshot, read_bound_text

ASSETS = Path(__file__).resolve().parents[1] / 'dashboard'


def make_server(workspace, *, port=0, host='127.0.0.1', include_git=False, assets=None,
                interactive=False, executor=None):
    if host != '127.0.0.1':
        raise ValueError('建模工作台仅绑定 127.0.0.1；不提供远程暴露模式')
    root = Path(workspace).resolve()
    asset_root = Path(assets) if assets is not None else ASSETS
    if executor is not None and not interactive:
        raise ValueError('AI 执行需要显式启用交互模式')
    interaction = None
    token = secrets.token_urlsafe(32) if interactive else None

    class Handler(BaseHTTPRequestHandler):
        server_version = 'MathModelCopilot/0.3'

        def log_message(self, format, *args):
            # Do not echo paths, user content, or query values into logs.
            return

        def read_body(self, length, seconds):
            deadline = time.monotonic() + seconds
            chunks = []
            while length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('请求接收超过总时限')
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(length)
                if not chunk:
                    raise ValueError('请求尚未完整接收')
                chunks.append(chunk)
                length -= len(chunk)
            return b''.join(chunks)

        def send(self, code, body, content_type='application/json; charset=utf-8'):
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8') if isinstance(body, dict) else body
            # Closing HTTP/1.0 with an unread request body can reset the socket
            # before Windows clients receive the error response. Drain only a
            # bounded, length-delimited body; never execute a rejected request.
            if self.command in {'POST','PUT','PATCH','DELETE'} and not getattr(self, '_body_consumed', False):
                self._body_consumed = True
                try:
                    length = int(self.headers.get('Content-Length','0'))
                    if 0 < length <= 65536 and not self.headers.get('Transfer-Encoding'):
                        self.read_body(length, 1)
                except (OSError, ValueError):
                    pass
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self, *, api=False):
            port = self.server.server_address[1]
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if self.headers.get('Host') not in hosts:
                self.send(403, {'ok': False, 'error':'untrusted_host', 'message':'仅允许本机来源'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + name for name in hosts}:
                self.send(403, {'ok': False, 'error':'cross_origin', 'message':'不允许跨站读取'})
                return False
            if api and self.headers.get('X-Copilot-Read') != '1':
                self.send(403, {'ok': False, 'error':'read_header_required', 'message':'缺少只读客户端标识'})
                return False
            return True

        def do_GET(self):
            request = urlsplit(self.path)
            if not self.allowed(api=request.path.startswith('/api/')):
                return
            try:
                if request.path == '/api/snapshot':
                    if request.query:
                        raise ValueError('快照接口不接受工作区或任意查询参数')
                    self.send(200, {'ok': True, 'result': snapshot(root, include_git=include_git)})
                elif request.path == '/api/tutorial':
                    from copilot_tutorial import catalog, lesson
                    if not request.query:
                        value = catalog()
                    else:
                        q = parse_qs(request.query, strict_parsing=True, keep_blank_values=True)
                        if set(q) != {'topic'} or len(q['topic']) != 1:
                            raise ValueError('教学只接受一个主题，不接受路径或工作区参数')
                        value = lesson(q['topic'][0])
                    self.send(200, {'ok': True, 'result': value})
                elif request.path == '/api/recap':
                    if request.query:
                        raise ValueError('复盘读取不接受用户目录、路径或其他项目参数')
                    from copilot_recap import overview
                    self.send(200, {'ok': True, 'result': overview(root)})
                elif request.path == '/api/interaction':
                    if request.query:
                        raise ValueError('意见接口不接受查询参数')
                    if interaction:
                        value = interaction.view()
                    else:
                        from copilot_store import Store
                        cp = Store(root / 'state/decision_log.json').read()['copilot']
                        value = {'enabled':False, 'revision':cp['revision'], 'project_id':cp['project_id'],
                            'requests':[], 'assistant':{'available':False, 'reason':'当前为只读模式'}}
                    self.send(200, {'ok':True, 'result':{**value, 'token':token}})
                elif request.path == '/api/file':
                    q = parse_qs(request.query, strict_parsing=True)
                    if set(q) != {'path','snapshot','revision','authority','observation'} or any(len(v) != 1 for v in q.values()):
                        raise ValueError('文件读取参数不完整或重复')
                    value = read_bound_text(root, q['path'][0], snapshot_id=q['snapshot'][0],
                        revision=int(q['revision'][0]), authority_sha256=q['authority'][0], file_observation_hash=q['observation'][0])
                    self.send(200, {'ok': True, 'result': value})
                else:
                    mapping = {'/':('index.html','text/html; charset=utf-8'),
                        '/app.js':('app.js','text/javascript; charset=utf-8'),
                        '/data.js':('data.js','text/javascript; charset=utf-8'),
                        '/workbench.js':('workbench.js','text/javascript; charset=utf-8'),
                        '/help.js':('help.js','text/javascript; charset=utf-8'),
                        '/interaction.js':('interaction.js','text/javascript; charset=utf-8'),
                        '/styles.css':('styles.css','text/css; charset=utf-8')}
                    if request.path not in mapping or request.query:
                        self.send(404, {'ok':False,'error':'not_found','message':'没有此只读资源'})
                        return
                    name, mime = mapping[request.path]
                    self.send(200, (asset_root / name).read_bytes(), mime)
            except ConflictError:
                self.send(409, {'ok':False,'error':'snapshot_conflict','message':'项目或文件已变化，请刷新快照'})
            except IntegrityError:
                self.send(409, {'ok':False,'error':'authority_untrusted','message':'权威状态不可信；请通过 CLI 恢复或核查 Git 保护'})
            except PermissionError:
                self.send(403, {'ok':False,'error':'permission_denied','message':'无权读取该项目文件'})
            except FileNotFoundError:
                self.send(404, {'ok':False,'error':'missing_project','message':'未找到项目或界面文件；请检查工作区和安装'})
            except (ValueError, UnicodeError, KeyError, TypeError):
                self.send(400, {'ok':False,'error':'invalid_request_or_data','message':'请求或项目数据无法读取，请检查 CLI 诊断'})
            except OSError:
                self.send(503, {'ok':False,'error':'read_failed','message':'暂时无法读取项目；当前页面不能视为最新状态'})

        def reject_write(self):
            self.send(405, {'ok':False,'error':'read_only','message':'本界面只读；修改请使用受控 CLI 事务'})

        def do_POST(self):
            if not interaction:
                return self.reject_write()
            if not self.allowed():
                return
            origins = {f'http://127.0.0.1:{self.server.server_address[1]}',
                       f'http://localhost:{self.server.server_address[1]}'}
            supplied = self.headers.get('X-Copilot-Write', '')
            if self.headers.get('Origin') not in origins or not secrets.compare_digest(supplied.encode('utf-8'), token.encode('ascii')):
                return self.send(403, {'ok':False, 'message':'写入会话或来源无效，请刷新本机页面'})
            if self.path != '/api/interaction':
                return self.send(404, {'ok':False, 'message':'没有此操作入口'})
            try:
                if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                    raise ValueError('仅接受有长度限制的 JSON 请求')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('请求大小无效，最多 64 KB')
                self._body_consumed = True
                data = self.read_body(length, 5)
                if len(data) != length:
                    raise ValueError('请求尚未完整接收')
                payload = json.loads(data.decode('utf-8'))
                result = interaction.submit(payload)
                self.send(200, {'ok':True, 'result':result})
            except ConflictError as exc:
                self.send(409, {'ok':False, 'message':str(exc)})
            except IntegrityError:
                self.send(409, {'ok':False, 'message':'权威状态检查未通过，未保存意见'})
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                self.send(400, {'ok':False, 'message':str(exc)})
            except OSError:
                self.send(503, {'ok':False, 'message':'意见暂未保存，请检查本地服务后重试'})

        do_PUT = do_PATCH = do_DELETE = do_OPTIONS = reject_write

    class Server(ThreadingHTTPServer):
        def server_close(self):
            if interaction:
                interaction.close()
            super().server_close()
    server = Server((host, port), Handler)
    server.daemon_threads = True
    if interactive:
        from copilot_interaction import Interaction
        try:
            interaction = Interaction(root, executor=executor)
        except Exception:
            server.server_close()
            raise
    return server


def serve(workspace, *, port=8765, include_git=False, interactive=False, assistant_codex=False, assistant_timeout=180):
    if assistant_codex and not interactive:
        raise ValueError('请同时启用 --interactive 后使用 --assistant-codex')
    from copilot_interaction import CodexExecutor
    executor = CodexExecutor(assistant_timeout) if assistant_codex else None
    server = make_server(workspace, port=port, include_git=include_git, interactive=interactive, executor=executor)
    print(json.dumps({'dashboard_url': f'http://127.0.0.1:{server.server_address[1]}', 'read_only':not interactive,
        'network_scope':'loopback only', 'git_enabled':include_git}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--git', action='store_true', help='Opt in to local Git observation; never fetch or push')
    args = parser.parse_args(argv)
    serve(args.workspace, port=args.port, include_git=args.git)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
