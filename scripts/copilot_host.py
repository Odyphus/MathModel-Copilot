"""Small, evidence-bearing capability probes; never update workflow authority."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from copilot_store import sync_error_message


CAPABILITIES = ("read_files", "write_files", "execute_python", "matlab", "word", "network", "parallel_agents")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _entry(status, reason, *, executed=False, ok=False, **evidence):
    return {"status": status, "evidence": [{"executed": executed, "ok": ok,
            "reason": reason, "observed_at": _now(), **evidence}]}


def probe(workspace) -> dict:
    """Probe local file I/O and this Python interpreter with disposable files.

    Network, MATLAB, Word and agent orchestration are intentionally unprobed.
    A Python child process is not evidence of a parallel LLM agent capability.
    Results describe this process/user/workspace at this time, not every host.
    """
    root = Path(workspace).resolve()
    capabilities = {name: _entry("unknown", "No execution probe for this capability") for name in CAPABILITIES}
    report = {"schema_version": "0.1", "host": {"platform": platform.system(),
              "python": sys.executable, "adapter": "local-process"},
              "probed_at": _now(), "workspace": str(root), "capabilities": capabilities}
    if not root.is_dir():
        for name in ("read_files", "write_files", "execute_python"):
            capabilities[name] = _entry("unavailable", "Workspace is not an existing directory", path=str(root))
        return report
    token = secrets.token_hex(16)
    try:
        with tempfile.TemporaryDirectory(prefix=".copilot-probe-", dir=root) as temporary:
            folder = Path(temporary)
            target = folder / "file-probe.txt"
            operation = "file_write"
            try:
                with target.open("xb") as handle:
                    handle.write(token.encode("ascii"))
                    handle.flush()
                    operation = "file_sync"
                    os.fsync(handle.fileno())
                capabilities["write_files"] = _entry("available", "Created and flushed a temporary file",
                                                       executed=True, ok=True, operation="file_write", path=str(root))
            except OSError as exc:
                reason = sync_error_message(exc) if operation == "file_sync" else str(exc)
                capabilities["write_files"] = _entry("unavailable", reason, executed=True,
                    operation=operation, errno=exc.errno, exception=type(exc).__name__,
                    original_error=str(exc), path=str(root))
            try:
                observed = target.read_bytes()
                ok = observed == token.encode("ascii")
                capabilities["read_files"] = _entry("available" if ok else "unavailable", "Read-back comparison",
                                                      executed=True, ok=ok, operation="file_read",
                                                      sha256=hashlib.sha256(observed).hexdigest(), path=str(root))
            except OSError as exc:
                capabilities["read_files"] = _entry("unavailable", str(exc), executed=True, operation="file_read")
            child = (
                "import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); value=sys.argv[2]; "
                "p.write_text(value,encoding='utf-8'); actual=p.read_text(encoding='utf-8'); "
                "assert actual==value; print(json.dumps({'token':actual,'python':sys.version.split()[0]}))"
            )
            argv = [sys.executable, "-I", "-B", "-c", child, str(folder / "python-probe.txt"), token]
            try:
                result = subprocess.run(argv, cwd=folder, capture_output=True, text=True,
                                        encoding="utf-8", timeout=5, check=False)
                try:
                    payload = json.loads(result.stdout)
                except (ValueError, TypeError):
                    payload = {}
                ok = result.returncode == 0 and payload.get("token") == token
                capabilities["execute_python"] = _entry("available" if ok else "unavailable",
                    "Child interpreter executed a temporary write/read assertion", executed=True, ok=ok,
                    operation="python_execute", executable=sys.executable, exit_code=result.returncode,
                    python_version=payload.get("python"), stderr=result.stderr[-2000:])
            except (OSError, subprocess.TimeoutExpired) as exc:
                capabilities["execute_python"] = _entry("unavailable", str(exc), executed=True,
                                                          operation="python_execute", executable=sys.executable)
    except OSError as exc:
        for name in ("read_files", "write_files", "execute_python"):
            if capabilities[name]["status"] == "unknown":
                capabilities[name] = _entry("unavailable", f"Isolated probe directory unavailable: {exc}")
    return report


def require(capabilities, required_names) -> list[str]:
    """Return blockers; available without successful execution evidence is invalid."""
    if isinstance(capabilities, dict) and "capabilities" in capabilities:
        capabilities = capabilities["capabilities"]
    if not isinstance(capabilities, dict):
        return ["Host capabilities must be an object"]
    if not isinstance(required_names, (list, tuple, set)) or any(not isinstance(n, str) or not n for n in required_names):
        return ["Required capability names must be a collection of nonempty strings"]
    blockers = []
    for name in sorted(set(required_names)):
        item = capabilities.get(name)
        if not isinstance(item, dict):
            blockers.append(f"{name}: unsupported or not reported")
            continue
        status = item.get("status", "unknown")
        evidence = item.get("evidence", [])
        executed = isinstance(evidence, list) and any(
            isinstance(row, dict) and row.get("executed") is True and row.get("ok") is True
            for row in evidence)
        if status != "available":
            blockers.append(f"{name}: {status}; a successful execution probe is required")
        elif not executed:
            blockers.append(f"{name}: available claim lacks successful execution evidence")
    return blockers
