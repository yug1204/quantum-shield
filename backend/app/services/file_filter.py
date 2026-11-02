"""File filtering + language detection for Phase 1 (Data Ingestion).

Pure standard library on purpose: no third-party imports, so it is trivially testable.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# extension -> language
SOURCE_EXTENSIONS: dict[str, str] = {
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".java": "java",
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
}

# crypto-relevant config / certificate files
CONFIG_EXTENSIONS: dict[str, str] = {
    ".pem": "certificate", ".crt": "certificate", ".cer": "certificate",
    ".key": "key", ".pub": "key",
    ".yaml": "config", ".yml": "config", ".json": "config", ".toml": "config",
    ".properties": "config", ".conf": "config", ".cfg": "config", ".ini": "config",
    ".xml": "config", ".env": "config",
}

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", "__pycache__",
    "build", "dist", "target", ".idea", ".vscode", ".tox", ".mypy_cache", ".pytest_cache",
    "vendor", "site-packages",
}

MAX_FILE_BYTES = 1_000_000  # 1 MB per file

# Light keyword hints so later phases (Shree / Yug) can prioritise files.
# This is NOT the detector - Phase 3 does the real analysis.
CRYPTO_HINT_PATTERNS: dict[str, re.Pattern[str]] = {
    "RSA": re.compile(r"\bRSA\b|rsa\.generate|RSA\.generate|\"RSA\"|rsa_", re.I),
    # no leading \b: Java names look like "SHA256withECDSA"
    "ECDSA": re.compile(r"ECDSA|secp256|prime256v1", re.I),
    "ECDH": re.compile(r"\bECDH\b|\bX25519\b", re.I),
    "DH": re.compile(r"\bDiffieHellman\b|\bDH_\w+", re.I),
    "DSA": re.compile(r"\bDSA\b"),
    "MD5": re.compile(r"\bmd5\b|MessageDigest\.getInstance\(\s*\"MD5\"", re.I),
    "SHA1": re.compile(r"\bsha-?1\b", re.I),
    "DES": re.compile(r"\b3?DES\b|DESede", re.I),
    "RC4": re.compile(r"\bRC4\b|\barc4\b", re.I),
}


@dataclass
class ScannedFile:
    path: str            # relative to repo root, always '/' separated
    language: str
    kind: str            # "source" | "config" | "certificate" | "key"
    size_bytes: int
    sha256: str
    line_count: int
    crypto_hints: list[str] = field(default_factory=list)


def classify(path: Path) -> tuple[str, str] | None:
    """Return (language, kind) or None if the file should be ignored."""
    ext = path.suffix.lower()
    if ext in SOURCE_EXTENSIONS:
        return SOURCE_EXTENSIONS[ext], "source"
    if ext in CONFIG_EXTENSIONS:
        kind = CONFIG_EXTENSIONS[ext]
        return ext.lstrip("."), kind
    return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_crypto_hints(text: str) -> list[str]:
    return sorted(name for name, pat in CRYPTO_HINT_PATTERNS.items() if pat.search(text))


def scan_directory(root: str | os.PathLike[str]) -> list[ScannedFile]:
    """Walk `root`, return metadata for every relevant file. Never executes anything."""
    root_path = Path(root).resolve()
    results: list[ScannedFile] = []

    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        # prune in-place so os.walk doesn't descend
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if full.is_symlink():
                continue
            info = classify(full)
            if info is None:
                continue
            try:
                size = full.stat().st_size
                if size > MAX_FILE_BYTES:
                    continue
                data = full.read_bytes()
            except OSError:
                continue

            language, kind = info
            text = data.decode("utf-8", errors="ignore")
            hints = find_crypto_hints(text) if kind in ("source", "config") else []
            rel = full.relative_to(root_path).as_posix()
            results.append(
                ScannedFile(
                    path=rel,
                    language=language,
                    kind=kind,
                    size_bytes=size,
                    sha256=_sha256(data),
                    line_count=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
                    crypto_hints=hints,
                )
            )
    return results


def summarize(files: list[ScannedFile]) -> dict:
    by_lang: dict[str, int] = {}
    for f in files:
        by_lang[f.language] = by_lang.get(f.language, 0) + 1
    return {
        "total_files": len(files),
        "by_language": dict(sorted(by_lang.items())),
        "files_with_crypto_hints": sum(1 for f in files if f.crypto_hints),
    }
