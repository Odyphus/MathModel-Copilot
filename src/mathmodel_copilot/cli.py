"""Console entry point; business behavior remains in scripts/copilot.py."""
from __future__ import annotations

import sys

from . import DISPLAY_VERSION, resource_root


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        print("MathModel Copilot " + DISPLAY_VERSION)
        return 0
    root = resource_root()
    if args == ["--resource-root"]:
        print(root)
        return 0
    # Legacy modules import siblings and locate resources relative to __file__.
    # This does not change cwd: user artifacts stay in the requested workspace.
    sys.path.insert(0, str(root / "scripts"))
    from copilot import main as core_main
    return core_main(args)
