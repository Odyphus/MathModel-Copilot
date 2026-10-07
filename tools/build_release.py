"""Build a deterministic, allowlisted review ZIP. Never uploads or publishes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_support import inventory, inventory_sha256, scan, selected_files


def build(output: Path, public=False, profile="source"):
    metadata = json.loads((ROOT / "RELEASE_METADATA.json").read_text(encoding="utf-8"))
    if public:
        raise ValueError("Public release is blocked: resolve rights, maintainer/repository identity, acceptance and explicit publication authorization; this tool creates review candidates only")
    files = inventory(ROOT, profile=profile)
    if profile == "runtime" and [item["path"] for item in files if Path(item["path"]).name == "SKILL.md"] != ["SKILL.md"]:
        raise ValueError("Runtime release requires exactly one root SKILL.md")
    if len(files) != len({item["path"].casefold() for item in files}):
        raise ValueError("Case-colliding source paths are not portable to Windows")
    findings = scan(ROOT, selected_files(ROOT, profile=profile))
    if findings:
        raise ValueError("Candidate privacy scan failed: " + json.dumps(findings, ensure_ascii=False))
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Output directory must be new or empty: " + str(output))
    output.mkdir(parents=True, exist_ok=True)
    stem = "MathModel-Copilot-v" + metadata["version"] + "-" + profile + "-review"
    archive = output / (stem + ".zip")
    if archive.exists():
        raise FileExistsError("Output already exists; select a fresh directory: " + str(archive))
    prefix = "mathmodel-copilot/"
    source_hash = inventory_sha256(files)
    manifest = {"schema": "mathmodel-copilot.review-manifest/v1", "version": metadata["version"],
                "distribution_profile": profile,
                "source_manifest_sha256": source_hash,
                "public_release_allowed": False, "blockers": metadata["release_blockers"], "files": files}
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for name, data in [(prefix + entry["path"], (ROOT / entry["path"]).read_bytes()) for entry in files] + [(prefix + "RELEASE_MANIFEST.json", encoded)]:
            member = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            handle.writestr(member, data)
    with zipfile.ZipFile(archive) as handle:
        if handle.testzip() is not None:
            raise ValueError("ZIP CRC verification failed")
        if len(handle.namelist()) != len(set(handle.namelist())):
            raise ValueError("ZIP contains duplicate paths")
        for item in files:
            if hashlib.sha256(handle.read(prefix + item["path"])).hexdigest() != item["sha256"]:
                raise ValueError("ZIP manifest hash mismatch")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "RELEASE_MANIFEST.json").write_bytes(encoded)
    (output / "SHA256SUMS.txt").write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
    if inventory(ROOT, profile=profile) != files:
        raise ValueError("Source changed during packaging; freeze the source and rebuild in a fresh output directory")
    result = {"archive": archive.name, "sha256": digest, "source_manifest_sha256": source_hash,
              "distribution_profile": profile,
              "files": len(files), "crc": "pass", "member_hashes": "pass", "privacy_scan": "pass",
              "source_unchanged_during_build": True, "installation": "not_executed", "public_release_allowed": False}
    (output / "build-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("source", "runtime"), default="source",
                        help="source: full review source; runtime: one discoverable Skill without build/tests/plugin shims")
    parser.add_argument("--public", action="store_true", help="Always refuses in this review-only release tool")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output, args.public, args.profile), ensure_ascii=False, indent=2))
    except (ValueError, FileExistsError) as exc:
        parser.exit(2, str(exc) + "\n")
