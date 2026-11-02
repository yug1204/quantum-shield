"""Safe repo cloning for Phase 1.

Uses the `git` CLI via subprocess (no shell) so it has no third-party dependency.
Only https GitHub URLs or local paths (for tests) are accepted.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")

CLONE_TIMEOUT_SEC = 120
MAX_ZIP_BYTES = 100 * 1024 * 1024        # 100 MB uncompressed
MAX_ZIP_MEMBERS = 20_000


class IngestionError(Exception):
    """User-facing error (bad URL, clone failed, bad zip...)."""


def parse_github_url(url: str) -> tuple[str, str]:
    m = GITHUB_URL_RE.match(url.strip())
    if not m:
        raise IngestionError("Only https://github.com/<owner>/<repo> URLs are allowed.")
    return m.group("owner"), m.group("repo")


def _new_dir(base: Path, label: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", label)[:60]
    d = base / f"{safe}-{uuid.uuid4().hex[:8]}"
    return d


def _git(args: list[str], cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SEC,
            check=True,
            # keep the normal environment (proxy, CA certs, HOME, SYSTEMROOT on Windows),
            # but never prompt for credentials. Hooks are disabled via core.hooksPath.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as e:
        raise IngestionError("git timed out") from e
    except subprocess.CalledProcessError as e:
        raise IngestionError(f"git failed: {e.stderr.strip()[:300]}") from e
    return out.stdout.strip()


def clone_repo(source: str, base_dir: Path, branch: str | None = None, *, allow_local: bool = False) -> tuple[Path, str]:
    """Shallow-clone `source` into base_dir. Returns (local_path, head_commit_sha).

    allow_local=True is only for tests (clone from a local path).
    """
    if branch is not None and not BRANCH_RE.match(branch):
        raise IngestionError("Invalid branch name.")

    if allow_local and Path(source).exists():
        label = Path(source).name
    else:
        owner, repo = parse_github_url(source)
        source = f"https://github.com/{owner}/{repo}.git"
        label = f"{owner}_{repo}"

    dest = _new_dir(base_dir, label)
    args = ["clone", "--depth", "1", "--no-tags", "-c", "core.hooksPath=/dev/null"]
    if branch:
        args += ["--branch", branch]
    args += ["--", source, str(dest)]
    try:
        _git(args)
        sha = _git(["rev-parse", "HEAD"], cwd=dest)
    except IngestionError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest, sha


def extract_zip(zip_path: Path, base_dir: Path, label: str = "upload") -> Path:
    """Extract a zip safely (zip-slip + zip-bomb protection)."""
    dest = _new_dir(base_dir, label)
    dest.mkdir(parents=True)
    dest_resolved = dest.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise IngestionError("Zip has too many files.")
            if sum(m.file_size for m in members) > MAX_ZIP_BYTES:
                raise IngestionError("Zip is too large when extracted.")
            for m in members:
                target = (dest / m.filename).resolve()
                if dest_resolved not in target.parents and target != dest_resolved:
                    raise IngestionError("Unsafe path in zip.")
            zf.extractall(dest)
    except zipfile.BadZipFile as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestionError("Not a valid zip file.") from e
    except IngestionError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest
