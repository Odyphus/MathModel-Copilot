"""Private experience records. Never a second modeling authority or a daemon."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from copilot_store import ConflictError, IntegrityError, atomic_write, digest, file_lock, utc_now

ID = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
COLLECTIONS = {"experiences", "lessons", "feedback"}
LIMIT = 8 * 1024 * 1024


def text(value, name, maximum=4000, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum or '\x00' in value:
        raise ValueError(f"{name} 必须是{'可空' if empty else '非空'}文本，最多 {maximum} 字符")
    return value


def user_directory():
    override = os.environ.get("MATHMODEL_COPILOT_DATA_DIR")
    if override:
        p = Path(override).expanduser()
        if not p.is_absolute():
            raise ValueError("MATHMODEL_COPILOT_DATA_DIR 必须是绝对路径")
        return p
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        if not base.is_absolute():
            base = Path.home() / ".local/share"
    return base / "mathmodel-copilot"


def _integer(value):
    return type(value) is int and value >= 0


def _safe_component(value):
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError("记录路径无效")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10))
    if (re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value != value.rstrip(" .")
            or value.split('.')[0].upper() in reserved):
        raise ValueError("记录路径含不明确的名称")
    return value


class ExperienceStorage:
    """Checksummed private records, CAS writes, read-only queries; no auth claims."""
    def __init__(self, workspace=None, user_data=None):
        self.workspace = Path(workspace or Path.cwd()).resolve()
        self.root = Path(user_data).expanduser().absolute() if user_data is not None else user_directory().absolute()
        self.binding = hashlib.sha256(os.path.normcase(str(self.workspace)).encode('utf-8')).hexdigest()
        self._check_root()

    def _check_root(self):
        # Personal records must not be in the contest project or a Git worktree.
        # A conservative refusal is preferable to silently tracking private text.
        try:
            self.root.resolve().relative_to(self.workspace)
        except ValueError:
            pass
        else:
            raise ValueError("个人记录目录必须位于建模项目之外；请另选本机用户目录")
        for path in (self.root, *self.root.parents):
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError("个人记录目录不能经过符号链接或目录联接")
            if (path / '.git').exists():
                raise ValueError("个人记录目录位于 Git 工作树内；请选择不参与 Git 的目录")
        if os.path.normcase(str(self.root.resolve())) != os.path.normcase(str(self.root)):
            raise ValueError("个人记录目录解析发生变化")

    def path(self, *parts):
        self._check_root()
        p = self.root
        for item in parts:
            p = p / _safe_component(item)
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                raise ValueError("个人记录不能通过链接读取或写入")
        if os.path.normcase(str(p.resolve())) != os.path.normcase(str(p)):
            raise ValueError("个人记录路径解析发生变化")
        return p

    def prepare_write(self):
        self._check_root()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != 'nt' and self.root.stat().st_mode & 0o077:
            raise ValueError('个人目录向其他系统用户开放；请使用仅本人可访问的目录（权限 700）')

    def _record_path(self, collection, record_id):
        if collection not in COLLECTIONS or not isinstance(record_id, str) or not ID.fullmatch(record_id):
            raise ValueError("记录集合或编号无效")
        return self.path(collection, record_id + '.json')

    @staticmethod
    def _load(p):
        if p.stat().st_size > LIMIT:
            raise ValueError("个人记录过大，未加载；请保留文件后检查")
        value = json.loads(p.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('schema_version') != 1
                or not _integer(value.get('record_revision')) or value['record_revision'] < 1
                or not isinstance(value.get('binding'), str)):
            raise IntegrityError("个人记录格式损坏或版本不支持；未重置原记录")
        check = dict(value)
        claimed = check.pop('record_hash', None)
        if claimed != digest(check):
            raise IntegrityError("个人记录校验不一致；请保留原文件后恢复，不作为可信事实读取")
        return value

    def read(self, collection, record_id, *, cross_project=False):
        p = self._record_path(collection, record_id)
        if not p.exists():
            return None
        value = self._load(p)
        if value['binding'] != self.binding and not (collection == 'lessons' and cross_project):
            raise ValueError("记录属于其他本地项目")
        return copy.deepcopy(value)

    def list(self, collection, *, cross_project=False):
        if collection not in COLLECTIONS or (cross_project and collection != 'lessons'):
            raise ValueError("不允许枚举其他项目的个人记录")
        folder = self.path(collection)
        if not folder.exists():
            return []
        found = []
        paths = sorted(folder.glob('*.json'))
        if len(paths) > 2000:
            raise ValueError("个人记录超过本次读取范围，请按编号读取或整理记录")
        for p in paths:
            self._record_path(collection, p.stem)
            value = self._load(p)
            if value['binding'] == self.binding or cross_project:
                found.append(copy.deepcopy(value))
        return found

    def write(self, collection, record_id, value, expected_revision=None):
        p = self._record_path(collection, record_id)
        if not isinstance(value, dict):
            raise ValueError("记录必须是 JSON 对象")
        if value.get('binding', self.binding) != self.binding:
            raise ValueError("不能写入其他项目的个人记录")
        self.prepare_write()
        with file_lock(self.path(collection, record_id + '.lock')):
            self._record_path(collection, record_id)
            old = self.read(collection, record_id)
            if old is None:
                if expected_revision is not None:
                    raise ConflictError("记录尚不存在，请重新读取")
                revision = 1
            else:
                if not _integer(expected_revision) or old['record_revision'] != expected_revision:
                    raise ConflictError("个人记录已变化，请重新读取后重试；未覆盖")
                revision = expected_revision + 1
            new = copy.deepcopy(value)
            new.update(schema_version=1, binding=self.binding, record_revision=revision)
            new.pop('record_hash', None)
            new['record_hash'] = digest(new)
            if len(json.dumps(new, ensure_ascii=False).encode('utf-8')) > LIMIT:
                raise ValueError("个人记录过大，未保存")
            atomic_write(self._record_path(collection, record_id), new)
            if self.read(collection, record_id) != new:
                raise IntegrityError("写后回读不一致，不能报告已保存")
            return copy.deepcopy(new)

    def settings(self):
        p = self.path('experience-settings.json')
        if not p.exists():
            return {'schema_version': 1, 'settings_revision': 0,
                    'tutorial': {'state': 'unknown', 'invite_policy': 'once'},
                    'recap_default': 'ask', 'project_overrides': {}, 'preferences': {},
                    'experience_reuse': False, 'guidance_mode': 'contextual'}
        if p.stat().st_size > LIMIT:
            raise IntegrityError("设置过大，未加载")
        value = json.loads(p.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('schema_version') != 1
                or not _integer(value.get('settings_revision'))):
            raise IntegrityError("个人设置损坏或版本不支持；不会自动重置")
        raw = dict(value)
        expected = raw.pop('settings_hash', None)
        if expected != digest(raw):
            raise IntegrityError("个人设置校验不一致；不会自动重置")
        self._validate_settings(value)
        return copy.deepcopy(value)

    @staticmethod
    def _validate_settings(value):
        if (value.get('recap_default') not in {'ask', 'on', 'off'}
                or value.get('guidance_mode') not in {'contextual', 'off'}
                or type(value.get('experience_reuse')) is not bool
                or not isinstance(value.get('project_overrides'), dict)
                or any(not re.fullmatch('[a-f0-9]{64}', k) or v not in {'ask','on','off'}
                       for k, v in value['project_overrides'].items())):
            raise ValueError("个人设置字段无效")
        tutorial = value.get('tutorial', {})
        if (not isinstance(tutorial, dict) or set(tutorial) != {'state','invite_policy'}
                or tutorial.get('state') not in {'unknown','offered','skipped','completed'}
                or tutorial.get('invite_policy') not in {'once','never'}):
            raise ValueError("教学设置无效")
        prefs = value.get('preferences')
        if not isinstance(prefs, dict) or set(prefs) - {'explanation_style','detail_level','open_workbench'}:
            raise ValueError("使用偏好字段无效")
        if ('explanation_style' in prefs and prefs['explanation_style'] not in {'plain_with_terms','technical'}
                or 'detail_level' in prefs and prefs['detail_level'] not in {'concise','balanced','detailed'}
                or 'open_workbench' in prefs and type(prefs['open_workbench']) is not bool):
            raise ValueError("使用偏好取值无效")

    def configure(self, patch, expected_revision, user_request):
        text(user_request, '设置依据', 2000)
        allowed = {'tutorial','recap_default','project_recap','preferences','experience_reuse','guidance_mode'}
        if not isinstance(patch, dict) or not patch or set(patch) - allowed:
            raise ValueError("设置包含未知字段或为空")
        self.prepare_write()
        with file_lock(self.path('settings.lock')):
            value = self.settings()
            if not _integer(expected_revision) or expected_revision != value['settings_revision']:
                raise ConflictError("个人设置已变化；请读取最新设置版本")
            for key, item in patch.items():
                if key == 'project_recap':
                    value['project_overrides'][self.binding] = item
                elif key in {'tutorial','preferences'}:
                    if not isinstance(item, dict):
                        raise ValueError("设置字段必须是对象")
                    value[key].update(copy.deepcopy(item))
                else:
                    value[key] = copy.deepcopy(item)
            self._validate_settings(value)
            value['settings_revision'] += 1
            value['last_user_request'] = user_request
            value['updated_at'] = utc_now()
            value.pop('settings_hash', None)
            value['settings_hash'] = digest(value)
            atomic_write(self.path('experience-settings.json'), value)
            if self.settings() != value:
                raise IntegrityError("个人设置未通过写后回读")
            return value

    def recording_enabled(self):
        value = self.settings()
        return value['project_overrides'].get(self.binding, value['recap_default']) == 'on'


def parser():
    p = argparse.ArgumentParser(description='教学、个人复盘与经验；不修改建模权威状态')
    p.add_argument('--workspace', type=Path, default=Path.cwd())
    p.add_argument('--user-data', type=Path, help='个人数据目录，必须位于建模项目和 Git 工作树之外')
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('settings', help='读取设置，无项目也可使用')
    s = sub.add_parser('configure', help='按本人明确要求更新个人设置')
    s.add_argument('--payload', type=Path, required=True)
    s.add_argument('--settings-revision', type=int, required=True)
    s.add_argument('--user-request', required=True)
    s = sub.add_parser('tutorial', help='随时进入功能教学；不会改项目或自动运行示例')
    s.add_argument('--topic', default='all')
    sub.add_parser('catalog', help='读取功能用途和入口')
    s = sub.add_parser('start', help='开启本段过程；必须已有项目记录许可或明确单次许可')
    s.add_argument('--goal', required=True)
    s.add_argument('--request-id', required=True)
    s.add_argument('--save-once', action='store_true')
    s.add_argument('--user-request')
    s = sub.add_parser('record', help='及时保留获准的关键过程，原话与转述分别登记')
    s.add_argument('--id', required=True)
    s.add_argument('--record-revision', type=int, required=True)
    s.add_argument('--payload', type=Path, required=True)
    s = sub.add_parser('recap', help='收尾生成复盘；来源变化产生新版本')
    s.add_argument('--id', required=True)
    s.add_argument('--record-revision', type=int, required=True)
    s.add_argument('--reason', choices=['goal_finished','handoff','stopped','failed','manual','recovered'], default='manual')
    s.add_argument('--payload', type=Path, help='可选：AI 分析/下一步；不允许伪造程序事实')
    s = sub.add_parser('resume', help='读取本项目复盘和当前事实，按授权匹配经验')
    s.add_argument('--tags', nargs='*', default=[])
    s = sub.add_parser('lesson-save', help='保存本人选定并允许跨项目参考的经验')
    s.add_argument('--payload', type=Path, required=True)
    s.add_argument('--user-request', required=True)
    s = sub.add_parser('lesson-withdraw', help='撤回本项目创建的经验')
    s.add_argument('--id', required=True)
    s.add_argument('--record-revision', type=int, required=True)
    s = sub.add_parser('lesson-edit', help='修改本人选定经验的内容、条件或复用范围')
    s.add_argument('--id', required=True)
    s.add_argument('--record-revision', type=int, required=True)
    s.add_argument('--payload', type=Path, required=True)
    s.add_argument('--user-request', required=True)
    sub.add_parser('lessons', help='查看本项目保存的经验，包括已撤回项')
    sub.add_parser('list', help='列出本项目个人复盘')
    s = sub.add_parser('export', help='显式导出选定复盘；不自动附到 GitHub')
    s.add_argument('--id', required=True)
    s.add_argument('--output', type=Path, required=True)
    s = sub.add_parser('forget', help='删除本人明确选定的复盘或经验，不删除比赛文件或远端反馈')
    s.add_argument('--collection', choices=['experiences','lessons'], required=True)
    s.add_argument('--id', required=True)
    s.add_argument('--record-revision', type=int, required=True)
    s.add_argument('--confirm', action='store_true', required=True)
    return p


def execute(args):
    if args.action in {'tutorial','catalog'}:
        from copilot_tutorial import lesson, catalog
        return lesson(args.topic) if args.action == 'tutorial' else catalog()
    store = ExperienceStorage(args.workspace, args.user_data)
    def payload():
        path = args.payload
        if path.stat().st_size > LIMIT:
            raise ValueError('输入材料过大')
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('输入材料必须是 JSON 对象')
        return value
    if args.action == 'settings':
        return store.settings()
    if args.action == 'configure':
        return store.configure(payload(), args.settings_revision, args.user_request)
    from copilot_recap import start, record_event, close, resume, save_lesson, withdraw_lesson, edit_lesson, export_recap, forget
    if args.action == 'start':
        return start(store, args.goal, args.request_id, save_once=args.save_once, user_request=args.user_request)
    if args.action == 'record':
        return record_event(store, args.id, args.record_revision, payload())
    if args.action == 'recap':
        return close(store, args.id, args.record_revision, args.reason, payload() if args.payload else {})
    if args.action == 'resume':
        return resume(store, args.tags)
    if args.action == 'lesson-save':
        return save_lesson(store, payload(), args.user_request)
    if args.action == 'lesson-withdraw':
        return withdraw_lesson(store, args.id, args.record_revision)
    if args.action == 'lesson-edit':
        return edit_lesson(store, args.id, args.record_revision, payload(), args.user_request)
    if args.action == 'lessons':
        return store.list('lessons')
    if args.action == 'list':
        return [{'id':r['id'],'goal':r['goal'],'state':r['state'],'record_revision':r['record_revision'],
                 'recaps':len(r['recaps'])} for r in store.list('experiences')]
    if args.action == 'export':
        return export_recap(store, args.id, args.output)
    if args.action == 'forget':
        return forget(store, args.collection, args.id, args.record_revision)
    raise ValueError('未知体验操作')


def main(argv=None):
    try:
        result = execute(parser().parse_args(argv))
        print(json.dumps({'ok':True,'result':result},ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'ok':False,'error':type(exc).__name__,'message':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 3 if isinstance(exc, ConflictError) else 4 if isinstance(exc, IntegrityError) else 2


if __name__ == '__main__':
    raise SystemExit(main())
