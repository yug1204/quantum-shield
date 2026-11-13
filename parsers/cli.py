"""Usage (from the quantum-shield folder):
    python -m parsers.cli sample_vulnerable_repo
    python -m parsers.cli path/to/any/code --out result.json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from backend.app.services.file_filter import scan_directory

from .project import parse_project


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse a code folder into AST summary + call graph JSON")
    ap.add_argument("folder")
    ap.add_argument("--out", help="write JSON here instead of printing the summary")
    args = ap.parse_args()

    files = [asdict(f) for f in scan_directory(args.folder)]
    result = parse_project(Path(args.folder), files)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"written: {args.out}")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
