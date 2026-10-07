"""Only custom resource copying; project metadata lives in pyproject.toml."""
from pathlib import Path
import sys

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_support import selected_files


class BuildWithResources(build_py):
    """Keep legacy script-relative resources together inside the wheel."""

    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        target = Path(self.build_lib) / "mathmodel_copilot" / "_payload"
        self._resource_outputs = []
        for relative in selected_files(root, payload=True):
            destination = target / relative
            self.mkpath(str(destination.parent))
            self.copy_file(str(root / relative), str(destination))
            self._resource_outputs.append(str(destination))

    def get_outputs(self, include_bytecode=1):
        return super().get_outputs(include_bytecode) + getattr(self, "_resource_outputs", [])


class SourceWithAllowlist(sdist):
    def make_release_tree(self, base_dir, files):
        root = Path(__file__).resolve().parent
        super().make_release_tree(base_dir, [str(p) for p in selected_files(root)])


setup(cmdclass={"build_py": BuildWithResources, "sdist": SourceWithAllowlist})
