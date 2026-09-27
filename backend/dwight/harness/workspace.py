"""Workspaces the Agent runs in: a fresh copy per Session.

Two kinds:
  * repo:    a checkout of the pinned open-source repo (OSS_REPO), for the
             real-layer engineering tasks (ticket 03).
  * kestrel: a copy of data/company/workspace/ (the fictional Customer's
             workspace with the `bin/blobctl` stub), for the storage cost
             reduction tasks (tickets 04 and 16).

The real `blobctl` script is moved OUT of the workspace into a private
directory, and `bin/blobctl` becomes a two-line shim that execs it. So the
Agent can run `bin/blobctl ...` but reading the workspace never shows the
stub's source (ticket 02: reading it would skip the trial and error that
produces the planted Discovery). The tools refuse to read it too (tools.py).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dwight import config

# The real open-source repo the real-layer tasks run against. Pinned so the
# runs are reproducible. tomli: a small, pure-Python TOML parser (MIT).
OSS_REPO = {
    "name": "tomli",
    "url": "https://github.com/hukkin/tomli",
    "tag": "2.4.1",
    "commit": "c5f44690c68c5ed29534faa8f9df18882113728c",
    "license": "MIT",
}

VAR_DIR = config.BACKEND_DIR / "var"                 # gitignored
OSS_DIR = VAR_DIR / "oss" / OSS_REPO["name"]         # the pinned clone
# Workspaces live OUTSIDE the repo, so tools such as pytest don't pick up the repo's
# own config (backend/pytest.ini) from an ancestor directory. Kept after the run for debugging.
HARNESS_DIR = Path(os.environ.get("DWIGHT_HARNESS_DIR") or Path(tempfile.gettempdir()) / "dwight-harness").resolve()
WORKSPACES_DIR = HARNESS_DIR / "workspaces"          # one fresh copy per Session
PRIVATE_DIR = HARNESS_DIR / "private"                # hidden blobctl implementations

KESTREL_WORKSPACE = config.COMPANY_DIR / "workspace"

BLOBCTL_SHIM = """#!/bin/sh
# blobctl: Kestrel storage lifecycle control plane client (managed by data-infra).
exec "$BLOBCTL_IMPL" "$@"
"""


@dataclass
class Workspace:
    root: Path
    kind: str                                  # repo | kestrel
    env: dict[str, str] = field(default_factory=dict)
    deny_read: tuple[str, ...] = ()            # workspace-relative paths the read tools refuse


def ensure_oss_repo() -> Path:
    """Clone the pinned repo into backend/var/oss/ if needed, at the pinned commit."""
    if not (OSS_DIR / ".git").exists():
        OSS_DIR.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", OSS_REPO["url"], str(OSS_DIR)], check=True)
    head = subprocess.run(["git", "-C", str(OSS_DIR), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    if head != OSS_REPO["commit"]:
        subprocess.run(["git", "-C", str(OSS_DIR), "checkout", "--quiet", OSS_REPO["commit"]], check=True)
    return OSS_DIR


def _base_env(root: Path) -> dict[str, str]:
    """A clean environment: no API keys, no STORAGE_ENV, HOME inside the workspace.
    The harness's Python (the backend venv) comes first on PATH, so `python` and
    `python -m pytest` work."""
    py_bin = str(Path(sys.executable).parent)
    tmp = root / ".tmp"
    tmp.mkdir(exist_ok=True)
    return {
        "PATH": os.pathsep.join([py_bin, "/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin"]),
        "HOME": str(root),
        "TMPDIR": str(tmp),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTEST_ADDOPTS": "-p no:cacheprovider",       # no cache files, deterministic output
        "NO_COLOR": "1",
        "TERM": "dumb",
    }


def _fresh_dir(session_id: str) -> Path:
    root = WORKSPACES_DIR / session_id
    if root.exists():
        shutil.rmtree(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    return root


def repo_workspace(session_id: str, extra_files: dict[str, str] | None = None) -> Workspace:
    """Fresh copy of the pinned OSS repo (without .git). `extra_files` (path -> text)
    are written into it, e.g. the planted failing test of a Runaway Loop task."""
    src = ensure_oss_repo()
    root = _fresh_dir(session_id)
    shutil.copytree(src, root, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    for rel, text in (extra_files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    env = _base_env(root)
    env["PYTHONPATH"] = str(root / "src")
    return Workspace(root=root.resolve(), kind="repo", env=env, deny_read=(".git",))


def kestrel_workspace(session_id: str) -> Workspace:
    """Fresh copy of data/company/workspace/ with bin/blobctl replaced by a shim."""
    root = _fresh_dir(session_id)
    shutil.copytree(KESTREL_WORKSPACE, root, ignore=shutil.ignore_patterns(".blobctl", "__pycache__"))
    impl_dir = PRIVATE_DIR / session_id
    if impl_dir.exists():
        shutil.rmtree(impl_dir)
    impl_dir.mkdir(parents=True)
    impl = impl_dir / "blobctl"
    shutil.move(str(root / "bin" / "blobctl"), impl)
    impl.chmod(0o755)
    shim = root / "bin" / "blobctl"
    shim.write_text(BLOBCTL_SHIM)
    shim.chmod(0o755)
    (root / "out").mkdir(exist_ok=True)
    env = _base_env(root)
    env["BLOBCTL_IMPL"] = str(impl.resolve())
    env["BLOBCTL_STATE_DIR"] = str((root / ".blobctl").resolve())
    return Workspace(root=root.resolve(), kind="kestrel", env=env, deny_read=("bin/blobctl",))
