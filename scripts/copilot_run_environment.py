"""Bound lock-file identity and observed execution metadata, not reproducibility proof."""
from __future__ import annotations
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

DEFAULT_PACKAGES = ("numpy", "scipy", "pandas", "scikit-learn", "sympy", "cvxpy", "pulp",
                    "highspy", "ortools", "osqp", "clarabel", "scs", "matplotlib", "openpyxl")


def bind_lock(root, value):
    from copilot_runtime import bind_file
    if isinstance(value, str):
        return bind_file(root, value)
    if not isinstance(value, dict) or set(value) - {"path", "sha256", "byte_size"}:
        raise ValueError("environment_lock 须为项目相对文件路径或 path/sha256 绑定")
    observed = bind_file(root, value.get("path"))
    if (not isinstance(value.get("sha256"), str) or value["sha256"].upper() != observed["sha256"]
            or "byte_size" in value and value["byte_size"] != observed["byte_size"]):
        raise ValueError("environment_lock 内容哈希/大小与声明不一致")
    return observed


def observe_git(root):
    """Observe real repository HEAD; never label a content hash as a Git commit."""
    executable = shutil.which("git")
    result = {"status": "unavailable", "head": "", "scope": "repository_head_not_execution_content"}
    if not executable:
        return result
    try:
        process = subprocess.run([executable, "-C", str(root), "rev-parse", "--verify", "HEAD"],
                                 capture_output=True, text=True, timeout=5, shell=False)
        head = process.stdout.strip()
        if process.returncode == 0 and re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", head):
            result.update(status="observed", head=head.lower())
        else:
            result["status"] = "not_available_for_workspace"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result


def observe_libraries(run_dir, environment, packages=DEFAULT_PACKAGES):
    """Ask the actual interpreter/cwd/environment for installed metadata.

    This does not import third-party modules or assert which backend the solver
    used. A local module shadow or native-library variant still needs review.
    """
    script = (
        "import importlib.metadata as m,json,platform,sys\n"
        "found={}\n"
        "for name in json.loads(sys.argv[1]):\n"
        " try: found[name]={'status':'installed','version':m.version(name)}\n"
        " except m.PackageNotFoundError: found[name]={'status':'not_installed','version':None}\n"
        "print(json.dumps({'status':'observed','python':sys.version,'executable':sys.executable,"
        "'platform':platform.platform(),'libraries':found}))\n"
    )
    scope = "installed_distribution_metadata_not_loaded_modules_or_determinism"
    try:
        process = subprocess.run([sys.executable, "-c", script, json.dumps(list(packages))],
                                 cwd=run_dir, env=environment, capture_output=True, text=True,
                                 encoding="utf-8", timeout=10, shell=False)
        if process.returncode != 0:
            return {"status": "unavailable", "scope": scope, "reason": "metadata probe failed",
                    "returncode": process.returncode}
        result = json.loads(process.stdout)
        if (not isinstance(result, dict) or result.get("executable") != sys.executable
                or set(result.get("libraries", {})) != set(packages)):
            raise ValueError("invalid metadata probe response")
        result["scope"] = scope
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "scope": scope, "reason": type(exc).__name__}
