"""Parse every supported file of an ingested project (output of Phase 1)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .graph import build_call_graph
from .java_parser import parse_java
from .python_parser import empty_result, parse_python

SCHEMA_VERSION = "1.0"
PARSERS = {"python": parse_python, "java": parse_java}
MAX_FILE_BYTES = 1_000_000


def parse_source(source: str, path: str, language: str) -> dict:
    return PARSERS[language](source, path)


def parse_project(local_path: str | Path, files: Iterable[dict]) -> dict:
    """`files` = items shaped like Phase 1 output: {"path", "language", "kind", ...}."""
    root = Path(local_path).resolve()
    parsed: list[dict] = []
    skipped: dict[str, int] = {}

    for f in files:
        if f.get("kind", "source") != "source":
            continue
        lang = f["language"]
        if lang not in PARSERS:
            skipped[lang] = skipped.get(lang, 0) + 1
            continue
        full = (root / f["path"]).resolve()
        if root not in full.parents:  # never read outside the project folder
            res = empty_result(f["path"], lang, "n/a")
            res["errors"].append("path outside project folder")
            parsed.append(res)
            continue
        try:
            if full.stat().st_size > MAX_FILE_BYTES:
                raise OSError("file too large")
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            res = empty_result(f["path"], lang, "n/a")
            res["errors"].append(str(e))
            parsed.append(res)
            continue
        parsed.append(parse_source(text, f["path"], lang))

    graph = build_call_graph(parsed)
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "files_parsed": len(parsed),
            "files_with_errors": sum(1 for p in parsed if p["errors"]),
            "skipped_unsupported_language": dict(sorted(skipped.items())),
            "classes": sum(len(p["classes"]) for p in parsed),
            "functions": len(graph["nodes"]),
            "calls": len(graph["edges"]) + sum(len(p["module_calls"]) for p in parsed),
            "resolved_edges": sum(1 for e in graph["edges"] if e["to_node"]),
        },
        "files": parsed,
        "call_graph": graph,
    }
