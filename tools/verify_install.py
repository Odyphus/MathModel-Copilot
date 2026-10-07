"""Verify a fresh source snapshot or review ZIP by building, installing and using it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import queue
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_support import inventory, inventory_sha256, scan, selected_files, verified_runtime_layout


def safe_member(name):
    value = PurePosixPath(name)
    if not name or value.is_absolute() or "\\" in name or ":" in name or ".." in value.parts or str(value) != name:
        raise ValueError("Unsafe archive member: " + name)
    return value


def unpack_review(archive_path: Path, destination: Path):
    """Check the full member set and every byte before extracting regular files."""
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(name.casefold() for name in names)):
            raise ValueError("Review ZIP has duplicate or case-colliding members")
        if archive.testzip() is not None:
            raise ValueError("Review ZIP CRC check failed")
        for item in archive.infolist():
            safe_member(item.filename)
            if item.is_dir() or ((item.external_attr >> 16) & 0o170000) not in (0, 0o100000):
                raise ValueError("Review ZIP must contain only regular files")
        prefix = "mathmodel-copilot/"
        manifest_name = prefix + "RELEASE_MANIFEST.json"
        manifest = json.loads(archive.read(manifest_name))
        if manifest.get("schema") != "mathmodel-copilot.review-manifest/v1":
            raise ValueError("Unknown review manifest schema")
        profile = manifest.get("distribution_profile", "source")
        if profile not in {"source", "runtime"}:
            raise ValueError("Unknown distribution profile")
        files = manifest["files"]
        wanted = [prefix + item["path"] for item in files] + [manifest_name]
        if len(wanted) != len(set(wanted)) or set(names) != set(wanted):
            raise ValueError("Review ZIP member set does not match its manifest")
        if manifest.get("source_manifest_sha256") != inventory_sha256(files):
            raise ValueError("Review ZIP manifest digest mismatch")
        for item in files:
            safe_member(item["path"])
            data = archive.read(prefix + item["path"])
            if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("Review ZIP member hash mismatch: " + item["path"])
        if destination.exists():
            raise FileExistsError("Extraction needs a fresh destination")
        destination.mkdir(parents=True)
        for name in names:
            path = destination.joinpath(*PurePosixPath(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(name))
    source = destination / "mathmodel-copilot"
    if inventory(source, profile=profile) != files or scan(source):
        raise ValueError("Extracted source violates the candidate allowlist or privacy scan")
    if profile == "runtime" and not verified_runtime_layout(source):
        raise ValueError("Runtime ZIP must have an exact inventory and one Skill entry")
    return source, manifest


def unpack_sdist(archive_path: Path, destination: Path):
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        roots, names = set(), set()
        for item in members:
            name = safe_member(item.name)
            folded = item.name.casefold()
            if folded in names or not (item.isfile() or item.isdir()):
                raise ValueError("Source distribution has duplicate or non-regular members")
            names.add(folded)
            roots.add(name.parts[0])
        if len(roots) != 1:
            raise ValueError("Source distribution needs exactly one root")
        destination.mkdir()
        for item in members:
            # Strip the one verified container directory to keep Windows build
            # paths short; every resource-relative path stays unchanged.
            path = destination.joinpath(*PurePosixPath(item.name).parts[1:])
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(item).read())
    return destination


def verify(output: Path, work: Path, archive_path: Path | None = None, virtualenv_path: Path | None = None):
    output, work = output.resolve(), work.resolve()
    if output == work or output in work.parents or work in output.parents:
        raise ValueError("Evidence and work directories must be separate")
    for path in (output, work):
        if path == ROOT or ROOT in path.parents or path in ROOT.parents:
            raise ValueError("Verification directories must be outside the source tree")
        if path.exists() and any(path.iterdir()):
            raise ValueError("Verification needs a new or empty directory: " + str(path))
        path.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    temp = work / "tmp"
    temp.mkdir()
    env.update(TEMP=str(temp), TMP=str(temp))
    report = {"schema": "mathmodel-copilot.install-verification/v1",
              "started_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "python": sys.version, "checks": [], "status": "running", "scope": "clean_installation_smoke",
              "full_regression_executed": False, "historical_fixtures_included": False,
              "remote_ci_executed": False, "published": False}

    def check(name, condition, detail=None):
        entry = {"name": name, "status": "pass" if condition else "fail"}
        if detail is not None:
            entry["detail"] = detail
        report["checks"].append(entry)
        if not condition:
            raise RuntimeError(name + " failed")

    def run(name, argv, cwd=work, expected=0, extra_env=None):
        start = time.monotonic()
        try:
            completed = subprocess.run([str(x) for x in argv], cwd=cwd, env=dict(env, **(extra_env or {})),
                                       capture_output=True, text=True, encoding="utf-8", timeout=300)
        except subprocess.TimeoutExpired as exc:
            report["checks"].append({"name": name, "status": "fail", "error": "timeout", "timeout_seconds": 300})
            (output / (name + ".stderr.log")).write_text(str(exc), encoding="utf-8")
            raise
        (output / (name + ".stdout.log")).write_text(completed.stdout, encoding="utf-8")
        (output / (name + ".stderr.log")).write_text(completed.stderr, encoding="utf-8")
        report["checks"].append({"name": name, "argv": [str(x) for x in argv], "returncode": completed.returncode,
                                 "expected_returncode": expected, "duration_seconds": round(time.monotonic() - start, 3),
                                 "status": "pass" if completed.returncode == expected else "fail"})
        if completed.returncode != expected:
            raise RuntimeError(name + " failed; see its log")
        return completed

    try:
        if archive_path is None:
            files = inventory(ROOT)
            check("source-privacy", not scan(ROOT))
            source = work / "source"
            source.mkdir()
            for item in files:
                target = source / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / item["path"], target)
            check("source-copy-hashes", inventory(source) == files)
            report["input"] = {"kind": "source_snapshot"}
        else:
            archive_path = archive_path.resolve()
            report["input"] = {"kind": "fresh_unzip", "archive": archive_path.name,
                               "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest()}
            source, manifest = unpack_review(archive_path, work / "fresh-unzip")
            files = manifest["files"]
            check("archive-crc-member-set-hashes-privacy", True, {"files": len(files)})
        metadata = json.loads((source / "RELEASE_METADATA.json").read_text(encoding="utf-8"))
        report["version"] = metadata["version"]
        report["source_manifest_sha256"] = inventory_sha256(files)
        report["release_blockers"] = metadata["release_blockers"]
        (output / "source-manifest.json").write_text(json.dumps(files, indent=2) + "\n", encoding="utf-8")
        if archive_path is not None and manifest.get("distribution_profile") == "runtime":
            # The user archive deliberately contains no wheel build inputs.
            # Execute the installed user path instead of labelling absent build
            # tools as a product failure or silently skipping its smoke checks.
            report.update(scope="runtime_zip_installation_smoke", distribution_profile="runtime",
                          wheel_build="not_applicable_runtime_distribution")
            skills = work / "isolated-skills"
            run("runtime-install", [sys.executable, "-B", source / "tools/install_skill.py", "--directory", skills])
            resource = skills / "mathmodel-copilot"
            check("runtime-one-discovery-entry", [p.relative_to(resource).as_posix() for p in resource.rglob("SKILL.md")] == ["SKILL.md"])
            check("runtime-installed-inventory", verified_runtime_layout(resource))
            project = work / "demo-project"
            command = [sys.executable, "-B", resource / "scripts/copilot.py", "--workspace", project]
            run("runtime-demo", command + ["demo"])
            before = (project / "state/decision_log.json").read_bytes()
            status = json.loads(run("runtime-status", command + ["status"]).stdout)["result"]
            check("runtime-demo-complete-not-formal-ready", status["requirements"]["complete"] and not status["submission"]["ready"])
            run("runtime-view", command + ["view"])
            run("runtime-host", command + ["host"])
            check("runtime-read-only-authority", before == (project / "state/decision_log.json").read_bytes())
            for competition in ("cumcm", "mcm", "diangong"):
                run("runtime-doctor-" + competition, [sys.executable, "-B", resource / "scripts/doctor.py", "--competition", competition, "--skip-tools"])
            run("runtime-no-overwrite", [sys.executable, "-B", resource / "tools/install_skill.py", "--directory", skills], expected=2)
            check("runtime-install-preserved", verified_runtime_layout(resource))
            check("runtime-unpacked-bytes-preserved", inventory(source, profile="runtime") == files)
            report.update(status="pass", workspace_preserved=True)
            return report
        report["build_tools"] = {name: importlib.metadata.version(name) for name in ("build", "setuptools", "wheel")}
        run("build", [sys.executable, "-B", "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", work / "dist", source])
        wheels, sdists = list((work / "dist").glob("*.whl")), list((work / "dist").glob("*.tar.gz"))
        check("distribution-count", len(wheels) == len(sdists) == 1)
        wheel, sdist = wheels[0], sdists[0]
        report["wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
        report["sdist_sha256"] = hashlib.sha256(sdist.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as package:
            check("wheel-crc", package.testzip() is None)
            names = package.namelist()
            check("wheel-no-official-assets-or-caches", not any("/examples/cumcm2018b/assets/" in name or name.endswith((".pdf", ".xls", ".png", ".pyc")) for name in names))
            payload = selected_files(source, payload=True)
            check("wheel-complete-resource-hashes", all(package.read("mathmodel_copilot/_payload/" + path.as_posix()) == (source / path).read_bytes() for path in payload), {"files": len(payload)})
        sdist_source = unpack_sdist(sdist, work / "s")
        check("sdist-source-hashes", inventory(sdist_source) == files)
        run("sdist-rebuild", [sys.executable, "-B", "-m", "build", "--no-isolation", "--wheel", "--outdir", work / "sdist-dist", sdist_source])
        rebuilt = next((work / "sdist-dist").glob("*.whl"))
        with zipfile.ZipFile(wheel) as first, zipfile.ZipFile(rebuilt) as second:
            check("sdist-wheel-member-equivalence", set(first.namelist()) == set(second.namelist()) and all(first.read(name) == second.read(name) for name in first.namelist()))
        environment = work / "venv"
        if virtualenv_path is None:
            venv.EnvBuilder(with_pip=True).create(environment)
            check("clean-environment-created", True, {"builder": "stdlib venv"})
        else:
            builder = virtualenv_path.resolve()
            report["virtualenv_builder_sha256"] = hashlib.sha256(builder.read_bytes()).hexdigest()
            run("clean-environment-created", [sys.executable, "-B", builder, "--copies", "--no-download",
                "--no-periodic-update", "--no-venv-redirect", "--app-data", work / "virtualenv-data", environment])
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command = environment / ("Scripts/mathmodel-copilot.exe" if os.name == "nt" else "bin/mathmodel-copilot")
        run("install", [python, "-B", "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile", rebuilt])
        packages = json.loads(run("installed-packages", [python, "-B", "-m", "pip", "list", "--format=json"]).stdout)
        check("core-no-third-party-runtime-dependencies", not ({item["name"].lower() for item in packages} - {"pip", "setuptools", "mathmodel-copilot"}), packages)
        version = run("version", [command, "--version"]).stdout
        check("module-and-console-entry-equivalent", run("module-version", [python, "-B", "-m", "mathmodel_copilot", "--version"]).stdout == version)
        resource = Path(run("resources", [command, "--resource-root"]).stdout.strip())
        check("resource-root-is-installed", environment in resource.parents)
        check("installed-resource-hashes", all((resource / path).read_bytes() == (source / path).read_bytes() for path in payload))
        for path in ("scripts/copilot.py", "references/copilot_runtime.md", "templates/shared/decision_log.json", "competitions/mcm/pack.json", "dashboard/index.html", "dashboard/app.js", "dashboard/data.js", "dashboard/styles.css"):
            check("resource-" + path.replace("/", "-"), (resource / path).is_file())
        project = work / "user-project"
        run("init", [command, "--workspace", project, "init", "--competition", "mcm"])
        authority = project / "state/decision_log.json"
        original = authority.read_bytes()
        run("init-resume", [command, "--workspace", project, "init", "--competition", "mcm"])
        run("status", [command, "--workspace", project, "status"])
        run("git-local-default", [command, "--workspace", project, "git", "status"])
        run("git-local-no-git", [command, "--workspace", project, "git", "status"], extra_env={"PATH": str(python.parent)})
        check("init-resume-and-reads-preserve-authority", authority.read_bytes() == original)
        demo = work / "demo-project"
        run("demo", [command, "--workspace", demo, "demo"])
        status = json.loads(run("demo-status", [command, "--workspace", demo, "status"]).stdout)["result"]
        check("demo-complete-requirements-not-formal-ready", status["requirements"]["complete"] and not status["submission"]["ready"])
        before = (demo / "state/decision_log.json").read_bytes()
        view = json.loads(run("view", [command, "--workspace", demo, "view"]).stdout)["result"]
        server = subprocess.Popen([str(command), "--workspace", str(demo), "dashboard", "--port", "0"], cwd=work, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        startup = queue.Queue()
        threading.Thread(target=lambda: startup.put(server.stdout.readline()), daemon=True).start()
        first_line = ""
        try:
            first_line = startup.get(timeout=30)
            server_info = json.loads(first_line)
            base = server_info["dashboard_url"]
            check("dashboard-cli-loopback", base.startswith("http://127.0.0.1:") and server_info["read_only"])
            with urllib.request.urlopen(base + "/", timeout=15) as response:
                check("dashboard-html", b"MathModel" in response.read())
            for asset in ("app.js", "data.js", "styles.css"):
                with urllib.request.urlopen(base + "/" + asset, timeout=15) as response:
                    check("dashboard-" + asset, bool(response.read()))
            request = urllib.request.Request(base + "/api/snapshot", headers={"X-Copilot-Read": "1"})
            with urllib.request.urlopen(request, timeout=30) as response:
                snapshot = json.load(response)
            check("dashboard-api", snapshot.get("ok") is True and isinstance(snapshot.get("result"), dict))
            check("dashboard-matches-cli-authority", all(snapshot["result"][key] == view[key] for key in ("authority_file_sha256", "revision", "project_id")))
            (output / "dashboard-snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            server.terminate()
            stdout, stderr = server.communicate(timeout=15)
            (output / "dashboard.stdout.log").write_text(first_line + stdout, encoding="utf-8")
            (output / "dashboard.stderr.log").write_text(stderr, encoding="utf-8")
        check("dashboard-state-unchanged", (demo / "state/decision_log.json").read_bytes() == before)
        skills = work / "isolated-skills"
        install_tool = resource / "tools/install_skill.py"
        run("skill-default", [python, "-B", install_tool, "--directory", skills])
        check("skill-default-name-only", (skills / "mathmodel-copilot/SKILL.md").is_file() and not (skills / "mathmodel-skill").exists())
        check("skill-default-exactly-one-entry", [p.relative_to(skills).as_posix() for p in skills.rglob("SKILL.md")] == ["mathmodel-copilot/SKILL.md"])
        skill_bytes = (skills / "mathmodel-copilot/SKILL.md").read_bytes()
        run("skill-refuse-overwrite", [python, "-B", install_tool, "--directory", skills], expected=2)
        check("skill-existing-bytes-preserved", (skills / "mathmodel-copilot/SKILL.md").read_bytes() == skill_bytes)
        aliases = work / "opt-in-skills"
        run("skill-explicit-compat", [python, "-B", install_tool, "--directory", aliases, "--legacy-alias"])
        check("skill-compat-sibling-link", "../mathmodel-copilot/SKILL.md" in (aliases / "mathmodel-skill/SKILL.md").read_text(encoding="utf-8"))
        collision = work / "upstream-skills"
        (collision / "mathmodel-skill").mkdir(parents=True)
        marker = collision / "mathmodel-skill/SKILL.md"
        marker.write_bytes(b"preserved upstream installation\n")
        run("skill-upstream-collision", [python, "-B", install_tool, "--directory", collision, "--legacy-alias"], expected=2)
        check("skill-collision-no-writes", marker.read_bytes() == b"preserved upstream installation\n" and not (collision / "mathmodel-copilot").exists())
        legacy = work / "legacy-copy"
        (legacy / "state").mkdir(parents=True)
        value = json.loads((resource / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
        value.pop("copilot", None)
        value["_schema_version"] = "3.1"
        legacy_bytes = (json.dumps(value, ensure_ascii=False, indent=3) + "\n").encode("utf-8")
        (legacy / "state/decision_log.json").write_bytes(legacy_bytes)
        run("legacy-migrate", [command, "--workspace", legacy, "migrate", "--expected-revision", "0"])
        check("migration-original-bytes-preserved", any(path.read_bytes() == legacy_bytes for path in (legacy / "state/migrations").glob("*.json")))
        run("legacy-status", [command, "--workspace", legacy, "status"])
        run("uninstall", [python, "-B", "-m", "pip", "uninstall", "-y", "mathmodel-copilot"])
        run("uninstalled", [python, "-B", "-c", "import importlib.util; assert importlib.util.find_spec('mathmodel_copilot') is None; print('package removed')"])
        check("uninstall-removes-payload", not resource.exists())
        check("uninstall-preserves-workspaces", (demo / "state/decision_log.json").read_bytes() == before and authority.read_bytes() == original)
        check("uninstall-preserves-migration-backup", any(path.read_bytes() == legacy_bytes for path in (legacy / "state/migrations").glob("*.json")))
        check("source-unchanged-during-verification", inventory(source) == files)
        report.update(status="pass", workspace_preserved=True, migration_original_bytes_preserved=True,
                      core_dependencies=[], resource_root_is_installed=True, dashboard_state_unchanged=True)
    except Exception as exc:
        report.update(status="fail", error=type(exc).__name__ + ": " + str(exc))
    finally:
        report["ended_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--archive", type=Path, help="Fresh-unzip and verify this exact source or runtime review ZIP")
    parser.add_argument("--virtualenv", type=Path, help="Optional local virtualenv.pyz when stdlib ensurepip is unavailable")
    args = parser.parse_args()
    try:
        result = verify(args.output, args.work_dir or args.output.with_name(args.output.name + "-work"), args.archive, args.virtualenv)
    except (ValueError, FileExistsError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "pass" else 1)
