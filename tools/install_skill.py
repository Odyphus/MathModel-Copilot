"""Create-only Skill discovery installation to an explicitly chosen directory."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_support import selected_files, inventory_sha256


def legacy_alias_text():
    # A thin optional entry, also available when installing from a runtime ZIP.
    return """---
name: mathmodel-skill
description: 显式启用的 MathModel Copilot 旧名称兼容入口，仅用于数学建模比赛。
---

# MathModel Copilot 旧名称入口

读取相邻的 `../mathmodel-copilot/SKILL.md`，以该文件为唯一工作流入口。
全部资源相对于 `../mathmodel-copilot/` 解析；主入口缺失时报告安装不完整。
"""


def install(directory: Path, legacy_alias=False):
    directory = directory.resolve()
    destination = directory / "mathmodel-copilot"
    alias = directory / "mathmodel-skill"
    for path in ([destination, alias] if legacy_alias else [destination]):
        if path.exists() or path.is_symlink():
            raise FileExistsError("Existing installation is never overwritten: " + str(path))
    if directory == ROOT or ROOT in directory.parents or destination == ROOT or destination in ROOT.parents:
        raise ValueError("Choose an installation directory outside the source tree")
    files = selected_files(ROOT, profile="runtime")
    if [path.as_posix() for path in files if path.name == "SKILL.md"] != ["SKILL.md"]:
        raise ValueError("Runtime installation requires exactly one root SKILL.md")
    metadata = json.loads((ROOT / "RELEASE_METADATA.json").read_text(encoding="utf-8"))
    directory.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    manifest = []
    for relative in files:
        source, target = ROOT / relative, destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        data = target.read_bytes()
        manifest.append({"path": relative.as_posix(), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (destination / "INSTALL_MANIFEST.json").write_text(json.dumps({"version": metadata["version"],
        "distribution_profile": "runtime", "source_manifest_sha256": inventory_sha256(manifest),
        "files": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if legacy_alias:
        alias.mkdir()
        (alias / "SKILL.md").write_text(legacy_alias_text(), encoding="utf-8")
    return {"installation": str(destination), "legacy_alias": str(alias) if legacy_alias else None,
            "overwritten": False, "workspace_changed": False, "distribution_profile": "runtime",
            "discovery_entries": 2 if legacy_alias else 1}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="Explicit Skill parent directory; no user/global default")
    parser.add_argument("--legacy-alias", action="store_true", help="Also create mathmodel-skill; refuses any existing path")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.directory, args.legacy_alias), indent=2))
    except (FileExistsError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
