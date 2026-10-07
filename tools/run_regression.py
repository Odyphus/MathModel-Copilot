"""Run unchanged unittest files and retain exact failures/skips as local evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_support import inventory, inventory_sha256


def run(output, pattern="test_*.py"):
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a new or empty evidence directory")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.dont_write_bytecode = True
    files = inventory(ROOT)
    started = datetime.now(timezone.utc).isoformat()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern)
    with (output / "unittest.log").open("w", encoding="utf-8") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    missing = [name for name in ("xlrd", "xlwt") if importlib.util.find_spec(name) is None]
    fixtures_present = (ROOT / "examples/cumcm2018b/assets/official_parameters.json").is_file()
    unchanged = inventory(ROOT) == files
    report = {"schema": "mathmodel-copilot.regression/v1", "started_utc": started,
              "ended_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
              "platform": platform.platform(), "pattern": pattern,
              "source_manifest_sha256": inventory_sha256(files), "source_unchanged": unchanged,
              "tests_run": result.testsRun, "failures": [{"test": test.id(), "traceback": tb} for test, tb in result.failures],
              "errors": [{"test": test.id(), "traceback": tb} for test, tb in result.errors],
              "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
              "historical_prerequisites": {"fixtures_present": fixtures_present, "missing_dependencies": missing},
              "full_acceptance": False, "remote_ci_executed": False, "published": False}
    report["status"] = "fail" if not result.wasSuccessful() or not unchanged else ("partial_pass" if result.skipped else "pass")
    report["scope"] = "Selected regression only; historical integration, platform coverage and final release acceptance require their own evidence"
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pattern", default="test_*.py")
    args = parser.parse_args()
    try:
        report = run(args.output, args.pattern)
    except ValueError as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["status"] == "fail" else 0)
