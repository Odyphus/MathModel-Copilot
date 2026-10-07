"""Installed launcher for the preserved MathModel Copilot resource tree."""
from pathlib import Path

__version__ = "0.3.0rc2"
DISPLAY_VERSION = "0.3.0-preview.2"


def resource_root() -> Path:
    installed = Path(__file__).resolve().parent / "_payload"
    source = Path(__file__).resolve().parents[2]
    root = installed if installed.is_dir() else source
    required = ("scripts/copilot.py", "templates/shared/decision_log.json", "competitions/generic/pack.json", "references/copilot_runtime.md")
    missing = [item for item in required if not (root / item).is_file()]
    if missing:
        raise RuntimeError("Incomplete MathModel Copilot installation: " + ", ".join(missing))
    return root
