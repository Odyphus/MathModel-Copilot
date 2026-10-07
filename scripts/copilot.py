#!/usr/bin/env python3
"""One public command surface for MathModel Copilot v0.1.

All state changes require an explicit baseline revision. Payload files are
structured data, never imported Python or shell commands. Output is JSON.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from copilot_store import ConflictError, IntegrityError, utc_now
from copilot_runtime import Runtime, project_status, safe_path, bind_file, SOURCE_KINDS
from copilot_context import build_context, acknowledge
from copilot_host import probe
from copilot_packs import load_pack
from copilot_domain import load_structured, impact_analysis
from copilot_payload import CONFIGURE_METADATA, TARGETS, check_keywords, payload_help


def parser():
    p = argparse.ArgumentParser(description="MathModel Copilot v0.3.0-preview.1 — versioned modeling, evidence and collaboration")
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = p.add_subparsers(dest="command", required=True)
    def command(name, help_text, mutation=False):
        s = sub.add_parser(name, help=help_text)
        if mutation:
            s.add_argument("--expected-revision", type=int, required=True)
            s.add_argument("--actor", default="integrator")
        return s
    s = command("init", "Create or resume, never overwrite an existing project")
    s.add_argument("--competition", default="generic")
    s.add_argument("--problem")
    s.add_argument("--team-size", type=int, default=3)
    s = command("demo", "Run the original synthetic historical MCM example in a new workspace")
    s.add_argument("--horizon", type=int, default=600, help="Simulation seconds, 12–3600; default is the full example")
    s = command("migrate", "Back up and migrate the existing authority", True)
    command("status", "Read the actual requirement, evidence and delivery state")
    s = command("report", "只读整理当前项目进展；可保存到新的 Markdown 文件")
    s.add_argument("--output", help="项目内新的 .md 相对路径；省略时在 JSON 的 markdown 字段返回，不覆盖已有文件")
    s = command("payload-help", "查看输入字段和示例，不修改项目状态")
    s.add_argument("target", choices=TARGETS)
    s.add_argument("--kind", help="register: ValidationPlan；interpretation / interpretation-review: AmbiguityEntry 或 AssumptionEntry")
    s = command("view", "Read the same revision-bound observation as the Dashboard")
    s.add_argument("--git", action="store_true", help="Opt in to local Git observation")
    s = command("dashboard", "Open a local, read-only project viewer")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--git", action="store_true", help="Opt in to local Git observation")
    s.add_argument("--interactive", action="store_true", help="Allow local versioned feedback; no direct model changes")
    s.add_argument("--assistant-codex", action="store_true", help="Opt in to bounded read-only Codex analysis from the page")
    s.add_argument("--assistant-timeout", type=int, default=180, help="Read-only AI time limit in seconds, 10–900")
    s = command("git", "Optional Git collaboration; proposals still use authority transactions")
    s.add_argument("arguments", nargs=argparse.REMAINDER)
    for name, label in (("experience", "教学、个人复盘和经验读取"),
                        ("usage-feedback", "使用反馈草稿、审阅与发送回执")):
        s = command(name, label + "；不修改建模权威状态")
        s.add_argument("arguments", nargs=argparse.REMAINDER)
    command("requirements", "Read the complete question and output matrix")
    command("host", "Probe actual local capabilities without changing project state")
    for name in ("configure", "task", "claim", "run", "decide", "rules-lock", "stage-record", "ai-log"):
        s = command(name, "Apply a structured payload through a versioned transaction", True)
        s.add_argument("--payload", required=True, help="项目内 JSON/YAML 文件；字段说明见 payload-help <命令>")
        if name == "task": s.add_argument("--id", required=True)
        if name == "run": s.add_argument("--request-id")
    s = command("register", "Register a versioned source contract or generated artifact", True)
    s.add_argument("--kind", choices=sorted(SOURCE_KINDS | {"ArtifactRecord"}), required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--payload", required=True)
    s.add_argument("--depends", nargs="*", default=[])
    s.add_argument("--files", nargs="*", default=[])
    s.add_argument("--request-id")
    s = command("transition", "Change a task state with dependency checks", True)
    s.add_argument("--id", required=True)
    s.add_argument("--state", choices=["pending", "running", "completed", "blocked"], required=True)
    s.add_argument("--outputs", nargs="*", default=[])
    s = command("interpretation", "登记题意歧义或建模假设的初始记录", True)
    s.add_argument("--kind", choices=["AmbiguityEntry", "AssumptionEntry"], required=True)
    s.add_argument("--payload", required=True, help="项目内 JSON/YAML；示例见 payload-help interpretation --kind 对象类型")
    s = command("interpretation-review", "记录歧义/假设的有依据处理，不推定用户已批准", True)
    s.add_argument("--id", required=True)
    s.add_argument("--payload", required=True, help="项目内 JSON/YAML；示例见 payload-help interpretation-review --kind 对象类型")
    s = command("validate", "Execute the predeclared independent checker", True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--payload", required=True)
    s = command("cover", "Map every required output to current verified evidence", True)
    s.add_argument("--requirement-id", required=True)
    s.add_argument("--payload", required=True)
    command("reconcile", "Record file drift and invalidate affected consumers", True)
    s = command("impact", "Read the dependency impact of changing an object")
    s.add_argument("--id", required=True)
    s = command("context", "Build a read-only Task Context and cumulative changes")
    s.add_argument("--role", choices=["modeler", "coder", "writer", "integrator", "qa"], required=True)
    s.add_argument("--member")
    s.add_argument("--task-id")
    s.add_argument("--since", type=int)
    s.add_argument("--output", help="New project-relative JSON file; existing files are never overwritten")
    s = command("ack", "Record received, adopted or explicitly reviewed facts", True)
    s.add_argument("--snapshot", required=True)
    s.add_argument("--member", required=True)
    s.add_argument("--action", choices=["received", "adopted", "verified"], required=True)
    s.add_argument("--objects", nargs="*", default=[])
    s.add_argument("--actor-kind", choices=["agent", "human", "agent_evaluator"], default="agent")
    s.add_argument("--note", default="")
    s.add_argument("--evidence")
    s = command("section", "Register a paper section with versioned claim markers", True)
    s.add_argument("--key", required=True)
    s.add_argument("--path", required=True)
    s.add_argument("--claims", nargs="*", required=True)
    s.add_argument("--source-bindings", help="JSON file containing typed source bindings")
    s.add_argument("--structure", help="JSON file containing figure/table/formula declarations")
    s = command("audit", "Run the checks on a concrete submission manifest", True)
    s.add_argument("--manifest", required=True)
    command("freeze", "Freeze a passing current delivery audit", True)
    s = command("package", "Build and verify a local allowlisted ZIP", True)
    s.add_argument("--path", required=True)
    s = command("delivery-event", "Record an explicit external action, never upload", True)
    s.add_argument("--state", choices=["awaiting_submission", "submitted", "receipt_received"], required=True)
    s.add_argument("--evidence")
    s.add_argument("--actor-kind", choices=["agent", "human"], default="agent")
    return p


def execute(args):
    root = args.workspace.resolve()
    rt = Runtime(root)
    def read_file(reference):
        data = load_structured(safe_path(root, reference))
        if not isinstance(data, dict):
            raise ValueError("payload 必须是 JSON/YAML object")
        return data
    cmd = args.command
    if cmd == "experience":
        from copilot_experience import execute as run_experience, parser as experience_parser
        return run_experience(experience_parser().parse_args(["--workspace", str(root), *args.arguments]))
    if cmd == "usage-feedback":
        from copilot_usage_feedback import execute as run_feedback, parser as feedback_parser
        return run_feedback(feedback_parser().parse_args(["--workspace", str(root), *args.arguments]))
    if cmd == "payload-help": return payload_help(args.target, args.kind)
    if cmd == "report":
        from copilot_summary import report
        return report(root, output=args.output)
    if cmd == "demo":
        import importlib.util
        entry = Path(__file__).resolve().parents[1] / "examples/mcm2009a/run_example.py"
        spec = importlib.util.spec_from_file_location("copilot_mcm_demo", entry)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.run_example(root, args.horizon)
    if cmd == "init":
        from init_workspace import initialize, normalize_problem
        pack = load_pack(args.competition)
        comp = pack["id"]
        problem = normalize_problem(comp, args.problem) if comp in {"cumcm", "mcm", "diangong"} else args.problem
        return initialize(root, comp, datetime.now(timezone.utc), problem=problem, team_size=args.team_size)
    if cmd == "migrate": return rt.migrate(args.expected_revision, actor=args.actor)
    if cmd == "status": return project_status(root, rt.read())
    if cmd == "view":
        from copilot_view import snapshot
        return snapshot(root, include_git=args.git)
    if cmd == "dashboard":
        from copilot_dashboard import serve
        serve(root, port=args.port, include_git=args.git, interactive=args.interactive,
              assistant_codex=args.assistant_codex, assistant_timeout=args.assistant_timeout)
        return {"stopped": True, "read_only": not args.interactive}
    if cmd == "git":
        from copilot_git import execute as execute_git, parser as git_parser
        return execute_git(git_parser().parse_args(["--workspace", str(root), *args.arguments]))
    if cmd == "requirements": return project_status(root, rt.read())["requirements"]
    if cmd == "host": return probe(root)
    if cmd == "configure":
        data = check_keywords(cmd, read_file(args.payload), rt.configure,
                              supplied={"revision", "actor"}, extra=CONFIGURE_METADATA)
        return rt.configure(args.expected_revision, actor=args.actor, **data)
    if cmd == "stage-record":
        data = check_keywords(cmd, read_file(args.payload), rt.record_stage, supplied={"revision", "actor"})
        return rt.record_stage(args.expected_revision, actor=args.actor, **data)
    if cmd == "ai-log": return rt.log_ai(args.expected_revision, read_file(args.payload), actor=args.actor)
    if cmd == "register":
        return rt.register(args.expected_revision, args.kind, args.key, read_file(args.payload),
                           dependencies=args.depends, files=args.files, actor=args.actor, request_id=args.request_id)
    if cmd == "task": return rt.task(args.expected_revision, args.id, read_file(args.payload), actor=args.actor)
    if cmd == "transition": return rt.transition(args.expected_revision, args.id, args.state, outputs=args.outputs, actor=args.actor)
    if cmd == "interpretation":
        return rt.record_interpretation(args.expected_revision, args.kind, read_file(args.payload), actor=args.actor)
    if cmd == "interpretation-review":
        data = check_keywords(cmd, read_file(args.payload), rt.review_interpretation,
                              supplied={"revision", "object_id", "actor"})
        return rt.review_interpretation(args.expected_revision, args.id, actor=args.actor, **data)
    if cmd == "run":
        data = check_keywords(cmd, read_file(args.payload), rt.execute, supplied={"revision", "actor", "request_id"})
        return rt.execute(args.expected_revision, actor=args.actor, request_id=args.request_id, **data)
    if cmd == "validate":
        data = check_keywords(cmd, read_file(args.payload), rt.validate_run, supplied={"revision", "run_id", "actor"})
        return rt.validate_run(args.expected_revision, args.run_id, actor=args.actor, **data)
    if cmd == "claim":
        data = read_file(args.payload)
        return rt.claim(args.expected_revision, data["claim"], data["results"], actor=args.actor)
    if cmd == "cover": return rt.cover(args.expected_revision, args.requirement_id, read_file(args.payload), actor=args.actor)
    if cmd == "reconcile": return rt.reconcile(args.expected_revision, actor=args.actor)
    if cmd == "impact":
        cp = rt.read()["copilot"]
        if args.id not in cp["objects"]: raise ValueError("对象不存在")
        edges = [{"from_id": dep, "to_id": oid, "invalidates": True} for oid, obj in cp["objects"].items() for dep in obj["dependencies"]]
        return impact_analysis(edges, args.id)
    if cmd == "context":
        result = build_context(root, role=args.role, task_id=args.task_id, member=args.member, since=args.since)
        if args.output:
            path = safe_path(root, args.output, exists=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
            return {"context_id": result["context_id"], "source_revision": result["source_revision"], "file": args.output}
        return result
    if cmd == "ack":
        return acknowledge(root, args.expected_revision, read_file(args.snapshot), member=args.member, action=args.action,
                           object_ids=args.objects, actor_kind=args.actor_kind, note=args.note, evidence=args.evidence)
    if cmd == "decide":
        data = read_file(args.payload)
        if not data.get("decision") or not data.get("reason"):
            raise ValueError("决策记录需 decision 与 reason")
        bindings = [bind_file(root, x) for x in data.get("evidence", [])]
        def change(state):
            entry = {"decision": data["decision"], "reason": data["reason"], "evidence": bindings, "at": utc_now(), "actor": args.actor}
            state["copilot"]["decisions"].append(entry)
            return entry
        return rt._tx(args.expected_revision, args.actor, "记录项目决策", change)
    from copilot_delivery import Delivery
    delivery = Delivery(root)
    if cmd == "rules-lock": return delivery.lock_rules(args.expected_revision, actor=args.actor, **read_file(args.payload))
    if cmd == "section":
        return delivery.section(args.expected_revision, args.key, args.path, args.claims, actor=args.actor,
            source_bindings=json.loads(safe_path(root, args.source_bindings).read_text(encoding="utf-8")) if args.source_bindings else None,
            structure=json.loads(safe_path(root, args.structure).read_text(encoding="utf-8")) if args.structure else None)
    if cmd == "audit": return delivery.audit(args.expected_revision, read_file(args.manifest), actor=args.actor)
    if cmd == "freeze": return delivery.freeze(args.expected_revision, actor=args.actor)
    if cmd == "package": return delivery.package(args.expected_revision, args.path, actor=args.actor)
    if cmd == "delivery-event": return delivery.event(args.expected_revision, args.state, args.evidence, args.actor_kind, args.actor)
    raise ValueError("未知命令")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        code = 3 if isinstance(exc, ConflictError) else 4 if isinstance(exc, IntegrityError) else 2
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return code


if __name__ == "__main__":
    raise SystemExit(main())
