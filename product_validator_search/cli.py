"""CLI helpers for running Product Validator tooling."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def web() -> None:
    """Run ADK web UI for this repository's agents directory.

    This is a convenience wrapper so users can run:
      uv run web
    instead of:
      uv run adk web .
    """
    repo_root = Path(__file__).resolve().parent.parent
    cmd = ["adk", "web", str(repo_root), *sys.argv[1:]]
    raise SystemExit(subprocess.run(cmd, check=False).returncode)
