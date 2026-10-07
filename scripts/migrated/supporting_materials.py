# Migrated from user-provided cumcm-workflow 1.6.0; see docs/MIGRATION.md.
"""Validate and package CUMCM supporting materials from an explicit whitelist.

The module never executes a submitted program or reproduction command.  Its
"smoke" checks are deliberately static: paths, hashes, sizes, ZIP membership,
CRC, anonymous run instructions, and the declared entry point are inspected.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree as ET


SCHEMA_VERSION = "cumcm.supporting_materials_manifest/v1"
MANIFEST_ARCHIVE_NAME = "supporting_materials_manifest.yaml"
OFFICIAL_NO_PROGRAM_STATEMENT = "本论文没有用到程序"
OFFICIAL_NO_SUPPORTING_STATEMENT = "本论文没有支撑材料"

HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:Users|home|mnt)/)")
IDENTITY_RE = re.compile(
    r"(?:(?:作者|姓名|学校|学院|学号|参赛队(?:号)?|队员[0-9一二三]?|"
    r"指导教师|手机号|联系电话|电子邮箱)\s*[：:]|"
    r"\b1[3-9]\d{9}\b|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    re.IGNORECASE,
)
FORBIDDEN_COMMAND_RE = re.compile(
    r"(?:^|\s)(?:curl|wget|powershell|pwsh|cmd|bash|sh|rm|del|erase|"
    r"remove-item|format|shutdown|invoke-webrequest)(?:\s|$)",
    re.IGNORECASE,
)
FORBIDDEN_COMPONENTS = {
    ".cumcm",
    "state",
    ".copilot",
    ".git",
    ".cache",
    ".pytest_cache",
    "__pycache__",
    "cache",
    "node_modules",
    "tmp",
    "temp",
}
ALLOWED_KINDS = {"code", "data", "figure", "table", "run_instructions", "evidence", "other"}
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_text_payload(text: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError("YAML manifest 需要 PyYAML；也可使用 JSON 兼容 YAML") from exc
        payload = yaml.safe_load(text)
    if not isinstance(payload, Mapping):
        raise ValueError("supporting materials manifest 顶层必须是对象")
    return payload


def load_manifest(path: str | Path) -> Mapping[str, Any]:
    return _load_text_payload(Path(path).read_text(encoding="utf-8-sig"))


def _official_statement_matches(value: Any, expected: str | None) -> bool:
    if expected is None:
        return isinstance(value, str) and len(value.strip()) >= 8
    text = re.sub(r"\s+", "", str(value or ""))
    return text.rstrip("。") == expected


def _safe_relative_path(value: Any) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, "路径为空"
    if "\\" in text:
        return None, "路径必须使用正斜杠"
    if text.startswith("/") or WINDOWS_DRIVE_RE.match(text):
        return None, "路径必须是安全相对路径"
    if "\x00" in text or any(ord(character) < 32 for character in text):
        return None, "路径含控制字符"
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None, "路径不得含空段、. 或 .."
    for part in path.parts:
        if ":" in part or part.endswith((" ", ".")):
            return None, "路径含 Windows 不安全文件名"
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
            return None, "路径含 Windows 保留设备名"
    normalized = path.as_posix()
    if normalized != text:
        return None, "路径不是规范相对路径"
    return normalized, None


def _path_policy_error(path: str, kind: str) -> str | None:
    pure = PurePosixPath(path)
    lowered_parts = {part.casefold() for part in pure.parts}
    forbidden = sorted(lowered_parts & FORBIDDEN_COMPONENTS)
    if forbidden:
        return f"路径包含禁止目录：{forbidden[0]}"
    if pure.suffix.casefold() == ".docx":
        return "支撑材料 ZIP 不得包含 DOCX"
    if (
        kind == "paper"
        or "论文" in pure.stem
        or "答卷" in pure.stem
        or re.search(r"(?:^|[_\-])paper(?:[_\-.]|$)", pure.name, re.I)
    ):
        return "支撑材料 ZIP 不得包含论文"
    if pure.name.casefold() == MANIFEST_ARCHIVE_NAME.casefold():
        return f"文件路径不得占用内置清单名 {MANIFEST_ARCHIVE_NAME}"
    return None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _static_command_error(command: Any, main_entry: str) -> str | None:
    text = str(command or "").strip()
    if not text:
        return "复现命令为空"
    if any(token in text for token in ("\n", "\r", ";", "&", "|", ">", "<", "`", "$(")):
        return "复现命令含 shell 控制符"
    if FORBIDDEN_COMMAND_RE.search(text):
        return "复现命令含禁止命令"
    if ABSOLUTE_PATH_RE.search(text):
        return "复现命令含绝对路径"
    normalized_entry = main_entry.replace("/", "\\")
    if main_entry not in text and normalized_entry not in text and PurePosixPath(main_entry).name not in text:
        return "复现命令未引用主入口"
    return None


def _source_path(project_root: Path, relative: str) -> tuple[Path | None, str | None]:
    candidate = project_root.joinpath(*PurePosixPath(relative).parts)
    if candidate.is_symlink():
        return None, "白名单文件不得是符号链接"
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(project_root.resolve(strict=True))
    except (FileNotFoundError, OSError, ValueError):
        return None, "文件不存在或逃逸项目根目录"
    if not resolved.is_file():
        return None, "路径不是普通文件"
    return resolved, None


def validate_manifest(
    manifest_path: str | Path,
    project_root: str | Path,
    *, no_program_statement: str | None = None,
    no_supporting_statement: str | None = None, check_identity: bool = True,
) -> dict[str, Any]:
    """Statically validate a whitelist manifest and every declared local file."""

    path = Path(manifest_path)
    root = Path(project_root)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        payload = load_manifest(path)
    except (OSError, ValueError) as exc:
        return {
            "passed": False,
            "mode": None,
            "errors": [f"清单无法读取：{exc}"],
            "warnings": [],
            "submitted_paths": [],
        }

    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}")

    mode = str(payload.get("mode", "")).strip()
    if mode not in {"package", "no_supporting_materials"}:
        errors.append("mode 必须为 package 或 no_supporting_materials")

    files = payload.get("files", [])
    if not isinstance(files, list):
        errors.append("files 必须是列表")
        files = []

    if mode == "no_supporting_materials":
        if files:
            errors.append("无支撑材料分支不得声明 files")
        if not _official_statement_matches(
            payload.get("official_no_supporting_statement"),
            no_supporting_statement,
        ):
            errors.append(f"无支撑材料分支必须使用官方原句：{no_supporting_statement}")
        program = payload.get("program")
        if not isinstance(program, Mapping) or program.get("mode") != "no_program":
            errors.append("无支撑材料分支必须同时显式声明 program.mode=no_program")
        elif not _official_statement_matches(
            program.get("official_no_program_statement"),
            no_program_statement,
        ):
            errors.append(f"无程序分支必须使用官方原句：{no_program_statement}")
        return {
            "passed": not errors,
            "mode": mode,
            "errors": errors,
            "warnings": warnings,
            "submitted_paths": [],
        }

    if mode == "package" and not files:
        errors.append("package 分支至少需要一个白名单文件")

    records: dict[str, Mapping[str, Any]] = {}
    submitted: list[str] = []
    for index, raw_record in enumerate(files, 1):
        label = f"files[{index}]"
        if not isinstance(raw_record, Mapping):
            errors.append(f"{label} 必须是对象")
            continue
        relative, path_error = _safe_relative_path(raw_record.get("path"))
        if path_error:
            errors.append(f"{label}.path：{path_error}")
            continue
        assert relative is not None
        if relative in records:
            errors.append(f"白名单路径重复：{relative}")
            continue
        records[relative] = raw_record

        kind = str(raw_record.get("kind", "")).strip()
        if kind not in ALLOWED_KINDS:
            errors.append(f"{relative} 的 kind 无效")
        policy_error = _path_policy_error(relative, kind)
        if policy_error:
            errors.append(f"{relative}：{policy_error}")

        purpose = str(raw_record.get("purpose", "")).strip()
        if not purpose:
            errors.append(f"{relative} 缺少用途 purpose")
        questions = _strings(raw_record.get("questions"))
        if not questions:
            errors.append(f"{relative} 缺少关联小问 questions")
        evidence_ids = _strings(raw_record.get("evidence_ids"))
        if not evidence_ids:
            errors.append(f"{relative} 缺少关联证据 evidence_ids")
        submit = raw_record.get("submit")
        if not isinstance(submit, bool):
            errors.append(f"{relative} 的 submit 必须是布尔值")
        elif submit:
            submitted.append(relative)

        declared_hash = str(raw_record.get("sha256", "")).strip()
        if not HASH_RE.fullmatch(declared_hash):
            errors.append(f"{relative} 的 SHA-256 无效")
        declared_size = raw_record.get("bytes")
        if not isinstance(declared_size, int) or isinstance(declared_size, bool) or declared_size < 0:
            errors.append(f"{relative} 的 bytes 必须是非负整数")

        source, source_error = _source_path(root, relative)
        if source_error:
            errors.append(f"{relative}：{source_error}")
            continue
        assert source is not None
        if isinstance(declared_size, int) and not isinstance(declared_size, bool):
            actual_size = source.stat().st_size
            if declared_size != actual_size:
                errors.append(f"{relative} 的 bytes 与文件不一致")
        if HASH_RE.fullmatch(declared_hash) and sha256_file(source) != declared_hash.upper():
            errors.append(f"{relative} 的 SHA-256 与文件不一致")

    run_instructions, run_error = _safe_relative_path(payload.get("run_instructions"))
    if run_error:
        errors.append(f"run_instructions：{run_error}")
    elif run_instructions not in records or run_instructions not in submitted:
        errors.append("匿名运行说明必须是已提交的白名单文件")
    else:
        if str(records[run_instructions].get("kind", "")) != "run_instructions":
            errors.append("run_instructions 对应文件的 kind 必须为 run_instructions")
        source, source_error = _source_path(root, run_instructions)
        if source_error:
            errors.append(f"运行说明：{source_error}")
        else:
            assert source is not None
            try:
                content = source.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"运行说明必须是 UTF-8 文本：{exc}")
            else:
                if (check_identity and IDENTITY_RE.search(content)) or ABSOLUTE_PATH_RE.search(content):
                    errors.append("运行说明包含身份信息或个人绝对路径")

    program = payload.get("program")
    if not isinstance(program, Mapping):
        errors.append("program 必须是对象")
        program = {}
    program_mode = str(program.get("mode", "")).strip()
    if program_mode == "code":
        main_entry, main_error = _safe_relative_path(program.get("main_entry"))
        if main_error:
            errors.append(f"program.main_entry：{main_error}")
        elif main_entry not in records or main_entry not in submitted:
            errors.append("主入口必须是已提交的白名单文件")
        else:
            if str(records[main_entry].get("kind", "")) != "code":
                errors.append("主入口文件的 kind 必须为 code")
            command_error = _static_command_error(program.get("reproduce_command"), main_entry)
            if command_error:
                errors.append(f"program.reproduce_command：{command_error}")
        unsubmitted_code = sorted(
            relative
            for relative, record in records.items()
            if str(record.get("kind", "")) == "code" and record.get("submit") is not True
        )
        if unsubmitted_code:
            errors.append(f"论文使用的源程序必须全部提交：{unsubmitted_code}")
    elif program_mode == "no_program":
        if not _official_statement_matches(
            program.get("official_no_program_statement"),
            no_program_statement,
        ):
            errors.append(f"无程序分支必须使用官方原句：{no_program_statement}")
        if str(program.get("main_entry", "")).strip() or str(program.get("reproduce_command", "")).strip():
            errors.append("无程序分支不得声明主入口或复现命令")
        code_records = sorted(
            relative
            for relative, record in records.items()
            if str(record.get("kind", "")) == "code"
        )
        if code_records:
            errors.append(f"无程序分支不得声明 code 文件：{code_records}")
    else:
        errors.append("program.mode 必须为 code 或 no_program")

    return {
        "passed": not errors,
        "mode": mode,
        "errors": errors,
        "warnings": warnings,
        "submitted_paths": sorted(submitted),
    }








def audit_supporting_zip(path: str | Path, *, max_zip_bytes: int | None = None) -> dict[str, Any]:
    """Verify size, CRC, manifest whitelist, membership, hashes, and sizes."""

    archive_path = Path(path)
    errors: list[str] = []
    members: list[str] = []
    if not archive_path.is_file():
        return {"passed": False, "errors": ["支撑材料 ZIP 不存在"], "members": []}
    if max_zip_bytes is not None and archive_path.stat().st_size > max_zip_bytes:
        errors.append(f"支撑材料 ZIP 超过 {max_zip_bytes} 字节")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                errors.append(f"ZIP CRC 失败：{bad_member}")
            infos = archive.infolist()
            members = [info.filename for info in infos]
            if len(members) != len(set(members)):
                errors.append("ZIP 含重复成员名")
            if len(members) != len({member.casefold() for member in members}):
                errors.append("ZIP 含 Windows 下冲突的大小写成员名")
            for info in infos:
                _, path_error = _safe_relative_path(info.filename)
                if path_error:
                    errors.append(f"ZIP 成员路径不安全：{info.filename}")
                if info.is_dir():
                    errors.append(f"ZIP 不应包含目录占位成员：{info.filename}")
                if info.flag_bits & 0x1:
                    errors.append(f"ZIP 不得包含加密成员：{info.filename}")
                unix_mode = info.external_attr >> 16
                if unix_mode & 0o170000 == 0o120000:
                    errors.append(f"ZIP 不得包含符号链接：{info.filename}")
            if MANIFEST_ARCHIVE_NAME not in members:
                errors.append(f"ZIP 缺少 {MANIFEST_ARCHIVE_NAME}")
                return {"passed": False, "errors": errors, "members": members}
            try:
                manifest = _load_text_payload(
                    archive.read(MANIFEST_ARCHIVE_NAME).decode("utf-8-sig")
                )
            except (KeyError, UnicodeDecodeError, ValueError) as exc:
                errors.append(f"ZIP 内清单无法读取：{exc}")
                return {"passed": False, "errors": errors, "members": members}
            if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("mode") != "package":
                errors.append("ZIP 内清单 schema_version 或 mode 无效")
            raw_files = manifest.get("files")
            if not isinstance(raw_files, list):
                errors.append("ZIP 内清单 files 必须是列表")
                raw_files = []
            expected: dict[str, Mapping[str, Any]] = {}
            unsubmitted: set[str] = set()
            for record in raw_files:
                if not isinstance(record, Mapping):
                    errors.append("ZIP 内清单含无效文件项")
                    continue
                relative, path_error = _safe_relative_path(record.get("path"))
                if path_error or relative is None:
                    errors.append("ZIP 内清单含不安全文件路径")
                    continue
                kind = str(record.get("kind", "")).strip()
                policy_error = _path_policy_error(relative, kind)
                if policy_error:
                    errors.append(f"ZIP 内清单路径违规：{relative}：{policy_error}")
                if relative in expected or relative in unsubmitted:
                    errors.append(f"ZIP 内清单路径重复：{relative}")
                if record.get("submit") is True:
                    expected[relative] = record
                else:
                    unsubmitted.add(relative)
            expected_members = set(expected) | {MANIFEST_ARCHIVE_NAME}
            actual_members = set(members)
            extras = sorted(actual_members - expected_members)
            missing = sorted(expected_members - actual_members)
            if extras:
                errors.append(f"ZIP 含白名单外文件：{extras}")
            if missing:
                errors.append(f"ZIP 缺少白名单文件：{missing}")
            leaked = sorted(actual_members & unsubmitted)
            if leaked:
                errors.append(f"ZIP 错含 submit=false 文件：{leaked}")
            for relative, record in expected.items():
                if relative not in actual_members:
                    continue
                data = archive.read(relative)
                if record.get("bytes") != len(data):
                    errors.append(f"ZIP 成员大小不匹配：{relative}")
                if str(record.get("sha256", "")).upper() != _sha256_bytes(data):
                    errors.append(f"ZIP 成员 SHA-256 不匹配：{relative}")
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        errors.append(f"ZIP 无法读取：{exc}")
    return {"passed": not errors, "errors": errors, "members": sorted(members)}




def _docx_text(path: Path) -> tuple[str, list[str]]:
    errors: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                return "", [f"DOCX ZIP CRC 失败：{bad_member}"]
            xml = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return "", [f"DOCX 无法读取：{exc}"]
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return "", [f"DOCX document.xml 无法解析：{exc}"]
    paragraphs = []
    for paragraph in root.iter(f"{{{W_NS}}}p"):
        paragraphs.append("".join(node.text or "" for node in paragraph.iter(f"{{{W_NS}}}t")))
    return "\n".join(paragraphs), errors


def audit_docx_appendix(
    docx_path: str | Path,
    manifest_path: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Check that the Word appendix lists exactly the submitted manifest paths."""

    text, errors = _docx_text(Path(docx_path))
    manifest = load_manifest(manifest_path)
    if errors:
        return {"passed": False, "errors": errors, "missing_paths": [], "unexpected_paths": []}
    paragraphs = text.splitlines()
    appendix_headings = [
        index
        for index, paragraph in enumerate(paragraphs)
        if re.fullmatch(
            r"附录(?:\s*[A-Z一二三四五六七八九十0-9]+)?(?:\s*[:：].+|\s+.+)?",
            paragraph.strip(),
        )
    ]
    if not appendix_headings:
        errors.append("DOCX 缺少附录")
        appendix = ""
    else:
        appendix = "\n".join(paragraphs[appendix_headings[0] :])

    mode = str(manifest.get("mode", ""))
    if mode == "no_supporting_materials":
        normalized_appendix = re.sub(r"\s+", "", appendix)
        if OFFICIAL_NO_SUPPORTING_STATEMENT not in normalized_appendix:
            errors.append(f"DOCX 附录缺少官方原句：{OFFICIAL_NO_SUPPORTING_STATEMENT}")
        if OFFICIAL_NO_PROGRAM_STATEMENT not in normalized_appendix:
            errors.append(f"DOCX 附录缺少官方原句：{OFFICIAL_NO_PROGRAM_STATEMENT}")
        return {"passed": not errors, "errors": errors, "missing_paths": [], "unexpected_paths": []}

    submitted = sorted(
        str(item.get("path", ""))
        for item in manifest.get("files", [])
        if isinstance(item, Mapping) and item.get("submit") is True
    )
    unsubmitted = sorted(
        str(item.get("path", ""))
        for item in manifest.get("files", [])
        if isinstance(item, Mapping) and item.get("submit") is False
    )
    missing = [path for path in submitted if path not in appendix]
    unexpected = [path for path in unsubmitted if path and path in appendix]
    if missing:
        errors.append(f"DOCX 附录漏列提交路径：{missing}")
    if unexpected:
        errors.append(f"DOCX 附录误列 submit=false 路径：{unexpected}")
    normalized_appendix = re.sub(r"\s+", "", appendix)
    source_root = (
        Path(project_root).resolve()
        if project_root is not None
        else Path(manifest_path).resolve().parent
    )
    for item in manifest.get("files", []):
        if not isinstance(item, Mapping) or item.get("submit") is not True:
            continue
        if str(item.get("kind", "")) != "code":
            continue
        relative = str(item.get("path", ""))
        source, source_error = _source_path(source_root, relative)
        if source_error:
            errors.append(f"无法核对附录中的源程序 {relative}：{source_error}")
            continue
        assert source is not None
        try:
            code_text = source.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                code_text = source.read_text(encoding="gb18030")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"源程序无法按文本核对 {relative}：{exc}")
                continue
        except OSError as exc:
            errors.append(f"源程序无法读取 {relative}：{exc}")
            continue
        normalized_code = re.sub(r"\s+", "", code_text)
        if not normalized_code or normalized_code not in normalized_appendix:
            errors.append(f"DOCX 附录未包含完整源程序：{relative}")
    return {
        "passed": not errors,
        "errors": errors,
        "missing_paths": missing,
        "unexpected_paths": unexpected,
    }








