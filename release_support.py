"""One allowlist shared by wheel, sdist and review ZIP creation.

No license decision is inferred from inclusion. Public redistribution is blocked
by RELEASE_METADATA.json until its factual prerequisites have been resolved.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

ROOT_FILES = {
    "AGENTS.md", "README.md", "SKILL.md", "LICENSE", "LICENSE_SCOPE.md",
    "THIRD_PARTY_NOTICES.md", "UPSTREAM.md", "CHANGELOG.md", "CONTRIBUTING.md",
    "SECURITY.md", "RELEASE_METADATA.json", "pyproject.toml", "setup.py",
    "release_support.py", ".gitignore", "PRODUCT.md", "DESIGN.md", "内测使用说明.md",
}
TREES = {".codex-plugin", ".github", "agents", "assets", "competitions", "config", "dashboard",
         "docs", "references", "scripts", "skills", "templates", "tests", "src", "tools", "compat"}
EXAMPLES = {"cumcm2018b", "mcm2009a", "v020_paper", "data_baselines", "forecast_paper"}
EXTRA_FILES = {".impeccable/design.json"}
EXCLUDED_FILES = {"assets/status-demo.svg"}
SUFFIXES = {".py", ".ps1", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".svg", ".html", ".css", ".js", ".tex", ".bib", ".cls", ".sty", ".csv"}
BLOCKED_PARTS = {"__pycache__", ".git", ".venv", "venv", "node_modules", "build", "dist",
                 ".pytest_cache", ".mypy_cache", "outputs", "cases", "verification", "work",
                 "screenshots", "mobbin", "data", ".copilot", "state", "paper_output", "paper_workspace"}
# Source references to these tokens are expected; actual secrets are not.
PRIVATE_PATH = re.compile(r"(?:[A-Za-z]:[/\\](?:Users|CodexData)[/\\]|[/]home[/][^/\s]+[/]|[/]Users[/][^/\s]+[/])")
SECRET = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)")


def selected_files(root: Path, *, payload=False, profile="source"):
    if profile not in {"source", "runtime"}:
        raise ValueError("Unknown release profile: " + str(profile))
    payload = payload or profile == "runtime"
    root = Path(root).resolve()
    selected = []
    # Path ordering differs on Windows (case-insensitive) and Linux. Release
    # manifests use a portable case-sensitive POSIX-name order on both.
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        parts = relative.parts
        # A user Skill has exactly one discovery entry. Plugin and legacy
        # discovery remain in the full source, not nested in a user install.
        if profile == "runtime" and parts[0] in {".codex-plugin", "skills", "compat"}:
            continue
        if relative.as_posix() in EXCLUDED_FILES:
            continue
        if path.is_symlink():
            raise ValueError("Release does not follow symlinks: " + relative.as_posix())
        if not path.is_file() or any(part.lower() in BLOCKED_PARTS or part.endswith(".egg-info") for part in parts):
            continue
        if parts[0] == "examples":
            if len(parts) < 3 or parts[1] not in EXAMPLES or "assets" in parts[2:]:
                continue
        elif len(parts) == 1:
            if path.name not in ROOT_FILES:
                continue
        elif parts[0] not in TREES and relative.as_posix() not in EXTRA_FILES:
            continue
        if len(parts) > 1 and path.suffix.lower() not in SUFFIXES and path.name != ".gitignore":
            continue
        if payload and parts[0] in {"src", "tests", ".github"}:
            continue
        if payload and path.name in {"setup.py", "pyproject.toml", "build_release.py", "verify_install.py", "run_regression.py"}:
            continue
        selected.append(relative)
    return selected


def inventory(root: Path, *, payload=False, profile="source"):
    root = Path(root).resolve()
    result = []
    for relative in selected_files(root, payload=payload, profile=profile):
        data = (root / relative).read_bytes()
        result.append({"path": relative.as_posix(), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return result


def verified_runtime_layout(root: Path):
    """Accept single-entry runtime layouts only with an exact byte inventory.

    Missing plugin metadata alone never turns an incomplete source checkout
    into a valid runtime package. This checks consistency, not publisher trust.
    """
    import json
    root = Path(root)
    for name in ("INSTALL_MANIFEST.json", "RELEASE_MANIFEST.json"):
        path = root / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if (isinstance(value, dict) and value.get("distribution_profile") == "runtime"
                    and value.get("files") == inventory(root)
                    and value.get("source_manifest_sha256") == inventory_sha256(value["files"])
                    and sorted(p.relative_to(root).as_posix() for p in root.rglob("SKILL.md")) == ["SKILL.md"]):
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return False


def inventory_sha256(files):
    """Identify the exact file set, independently of archive timestamps."""
    import json
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scan(root: Path, files=None):
    findings = []
    for relative in files if files is not None else selected_files(root):
        text = (root / relative).read_text(encoding="utf-8", errors="replace")
        for name, pattern in (("private_absolute_path", PRIVATE_PATH), ("credential", SECRET)):
            if pattern.search(text):
                findings.append({"path": relative.as_posix(), "finding": name})
    return findings
