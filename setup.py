"""Build hook that ships the prebuilt React dashboard inside the wheel.

Project metadata lives in pyproject.toml. The dashboard is built with npm into
``dashboard/dist`` (``cd dashboard && npm ci && npm run build``); this hook copies
it to ``agentmesh/dashboard_dist`` so ``pip install agentmesh-ai`` serves the full UI.

Set ``AGENTMESH_REQUIRE_DASHBOARD=1`` to fail the build instead of producing a
wheel without the dashboard (the release workflow does this).
"""

import os
import shutil
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
DASHBOARD_DIST = ROOT / "dashboard" / "dist"


class build_py_with_dashboard(build_py):
    def run(self) -> None:
        super().run()
        if getattr(self, "editable_mode", False):
            # Editable installs serve dashboard/dist straight from the checkout.
            return
        if not (DASHBOARD_DIST / "index.html").is_file():
            message = "dashboard/dist/index.html not found: run `npm ci && npm run build` in dashboard/ before building."
            if os.getenv("AGENTMESH_REQUIRE_DASHBOARD") == "1":
                raise SystemExit(f"error: {message}")
            sys.stderr.write(f"warning: {message} The wheel will only contain the minimal fallback dashboard.\n")
            return
        target = Path(self.build_lib) / "agentmesh" / "dashboard_dist"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(DASHBOARD_DIST, target)


setup(cmdclass={"build_py": build_py_with_dashboard})
