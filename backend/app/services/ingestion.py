"""Phase 1 pipeline: clone/extract -> scan -> JSON in the shared parser schema.

This module is framework-free. The FastAPI router and the DB layer call it.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .file_filter import ScannedFile, scan_directory, summarize
from .git_service import clone_repo, extract_zip

SCHEMA_VERSION = "1.0"


def build_ingestion_result(source: str, local_path: Path, commit: str | None, files: list[ScannedFile]) -> dict:
    """Shared JSON contract that Ritesh (Phase 2) reads. See schemas/ingestion_output.schema.json."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "local_path": str(local_path),
        "commit": commit,
        "summary": summarize(files),
        "files": [asdict(f) for f in files],
    }


def ingest_github(url: str, base_dir: Path, branch: str | None = None, *, allow_local: bool = False) -> dict:
    path, sha = clone_repo(url, base_dir, branch, allow_local=allow_local)
    files = scan_directory(path)
    return build_ingestion_result(url, path, sha, files)


def ingest_zip(zip_path: Path, base_dir: Path, label: str = "upload") -> dict:
    path = extract_zip(zip_path, base_dir, label)
    files = scan_directory(path)
    return build_ingestion_result(f"upload:{label}", path, None, files)
