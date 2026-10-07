#!/usr/bin/env python3
"""Re-run local acceptance and retain per-test evidence; no network or install."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import unittest


TEST_DEPENDENCIES = {
    "yaml": "PyYAML", "unidiff": "unidiff", "numpy": "numpy", "scipy": "scipy",
    "pandas": "pandas", "openpyxl": "openpyxl", "matplotlib": "matplotlib", "seaborn": "seaborn",
    "sklearn": "scikit-learn", "reportlab": "reportlab", "docx": "python-docx",
    "pypdf": "pypdf", "PIL": "Pillow", "xlrd": "xlrd", "xlwt": "xlwt",
}


def classify_outcome(status, reason, missing_modules=()):
    """Separate product failures, unavailable dependencies and deliberate skips."""
    reason = reason or ""
    if status == "pass":
        return "passed"
    if status in {"fail", "subtest_fail"}:
        return "assertion_failure"
    if status == "error":
        missing = re.search(r"^\s*(?:ModuleNotFoundError|ImportError): No module named ['\"]([^'\"]+)", reason, re.M)
        return ("dependency_missing" if missing and missing.group(1).split(".")[0] in missing_modules
                else "code_error")
    if status == "skip":
        if reason.startswith("historical_fixture_missing:"):
            return "fixture_missing"
        names_dependency = any(re.search(r"\b" + re.escape(module) + r"\b", reason, re.I)
                               for module in missing_modules)
        says_missing = re.search(r"\b(?:requires? optional|not installed|not available|unavailable|missing|not found)\b", reason, re.I)
        if reason.startswith("dependency_missing:") or names_dependency and says_missing:
            return "dependency_missing"
        if any(word in reason.lower() for word in ("xelatex", "ctexart", "not installed")):
            return "external_tool_missing"
        return "explicit_skip"
    return "code_error"


def verification_outcome(result, missing_modules, commands):
    """A successful selected check is not complete release acceptance."""
    success = result.wasSuccessful() and all(item["returncode"] == 0 for item in commands)
    partial = bool(result.skipped or missing_modules or not result.testsRun)
    return {"success": success, "status": "fail" if not success else "partial_pass" if partial else "pass",
            "full_acceptance": False,
            "scope": "Selected local checks only; success describes executed checks, not full release acceptance"}


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self.started = 0
    def startTest(self, test):
        self.started = time.perf_counter()
        super().startTest(test)
    def record(self, test, status, reason=None):
        self.records.append({"id": test.id(), "status": status, "reason": reason,
                             "elapsed_seconds": round(time.perf_counter() - self.started, 4)})
    def addSuccess(self, test):
        self.record(test, "pass"); super().addSuccess(test)
    def addFailure(self, test, err):
        self.record(test, "fail", self._exc_info_to_string(err, test)); super().addFailure(test, err)
    def addError(self, test, err):
        self.record(test, "error", self._exc_info_to_string(err, test)); super().addError(test, err)
    def addSkip(self, test, reason):
        self.record(test, "skip", reason); super().addSkip(test, reason)
    def addSubTest(self, test, subtest, err):
        if err is not None:
            status = "fail" if issubclass(err[0], test.failureException) else "error"
            self.record(subtest, status, self._exc_info_to_string(err, subtest))
        super().addSubTest(test, subtest, err)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skill-validator", type=Path)
    parser.add_argument("--temp-dir", type=Path, default=Path.cwd() / "work/verify-temp")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "verification.json").exists():
        parser.error("output-dir already contains a verification report; choose a new directory")
    os.environ["PYTHONUTF8"] = "1"
    os.environ["MPLBACKEND"] = "Agg"
    temporary = args.temp_dir.resolve()
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(temporary / "matplotlib")
    os.environ["TEMP"] = os.environ["TMP"] = str(temporary)
    sys.path.insert(0, str(root / "scripts"))
    sys.path.insert(0, str(root / "tests"))
    versions = {}
    for name in TEST_DEPENDENCIES.values():
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = None
    missing_modules = [module for module, package in TEST_DEPENDENCIES.items() if versions[package] is None]
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
    started = time.perf_counter()
    with (out / "unittest.log").open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordedResult).run(suite)
    test_elapsed = round(time.perf_counter() - started, 3)
    for record in result.records:
        record["classification"] = classify_outcome(record["status"], record["reason"], missing_modules)
    commands = []
    def run(name, command):
        begin = time.perf_counter()
        try:
            proc = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            (out / (name + ".log")).write_text(proc.stdout + proc.stderr, encoding="utf-8")
            item = {"name": name, "argv": command, "returncode": proc.returncode,
                    "elapsed_seconds": round(time.perf_counter()-begin, 3)}
        except (OSError, subprocess.TimeoutExpired) as exc:
            item = {"name": name, "argv": command, "returncode": None, "error": str(exc)}
        commands.append(item)
    run("compile", [sys.executable, "-m", "compileall", "-q", "scripts", "templates/shared/code_starter", "examples"])
    for comp in ("cumcm", "mcm", "diangong"):
        run("doctor-" + comp, [sys.executable, "-B", "scripts/doctor.py", "--competition", comp, "--skip-tools", "--json"])
    run("doctor-tools", [sys.executable, "-B", "scripts/doctor.py", "--competition", "cumcm", "--json"])
    if args.skill_validator:
        run("skill-validate", [sys.executable, "-B", str(args.skill_validator.resolve()), str(root)])
        run("primary-entry-validate", [sys.executable, "-B", str(args.skill_validator.resolve()), str(root / "skills/mathmodel-copilot")])
        run("explicit-compat-entry-validate", [sys.executable, "-B", str(args.skill_validator.resolve()), str(root / "compat/mathmodel-skill")])
    run("diff-check", ["git", "diff", "--check"])
    report = {"at": datetime.now(timezone.utc).isoformat(), "python": sys.version, "platform": platform.platform(),
              "executable": sys.executable, "dependencies": versions, "test_count": result.testsRun,
              "missing_test_dependencies": [TEST_DEPENDENCIES[module] for module in missing_modules],
              "passed": sum(x["status"] == "pass" for x in result.records), "skipped": len(result.skipped),
              "failures": len(result.failures), "errors": len(result.errors),
              "test_elapsed_seconds": test_elapsed,
              "classifications": {kind: sum(x["classification"] == kind for x in result.records)
                  for kind in ("passed", "assertion_failure", "code_error", "dependency_missing", "external_tool_missing", "fixture_missing", "explicit_skip")},
              "elapsed_seconds": round(time.perf_counter() - started, 3), "tests": result.records,
              "commands": commands, **verification_outcome(result, missing_modules, commands)}
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"tests", "dependencies", "commands", "python"}}, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__": raise SystemExit(main())
