"""Call graph from parsed files (best effort, name based).

Node id = "<file path>::<function id>". An edge is resolved (`to_node` set) only when the
target can be found with reasonable confidence; everything else stays as an external/unresolved
call (e.g. library calls like hashlib.md5), which is exactly what the crypto detector wants.
"""
from __future__ import annotations

from collections import defaultdict

SELF_NAMES = {"self", "cls", "this", "super"}


def build_call_graph(file_results: list[dict]) -> dict:
    nodes: list[dict] = []
    by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_qual: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for fr in file_results:
        for fn in fr["functions"]:
            node = {
                "id": f"{fr['path']}::{fn['id']}",
                "path": fr["path"],
                "language": fr["language"],
                "qualname": fn["qualname"],
                "name": fn["name"],
                "class": fn.get("class"),
                "line": fn["line"],
            }
            nodes.append(node)
            by_name[(fr["language"], fn["name"])].append(node)
            by_qual[(fr["language"], fn["qualname"])].append(node)

    def resolve(caller: dict, call: dict) -> str | None:
        parts = call["name"].split(".")
        if any(("()" in p or "[]" in p or p == "?") for p in parts[:-1]):
            return None
        lang, last = caller["language"], parts[-1]

        if len(parts) == 1 or (len(parts) == 2 and parts[0] in SELF_NAMES):
            cands = by_name.get((lang, last), [])
            same_file = [c for c in cands if c["path"] == caller["path"]]
            same_class = [c for c in same_file if c["class"] == caller["class"]]
            for pool in (same_class, same_file):
                if len(pool) >= 1:
                    return pool[0]["id"]
            if len(cands) == 1:
                return cands[0]["id"]
            return None

        qual = ".".join(parts[-2:])
        cands = [c for c in by_qual.get((lang, qual), [])]
        if not cands:  # allow nested classes: Outer.Inner.method
            cands = [c for (l, q), lst in by_qual.items() if l == lang and q.endswith("." + qual) for c in lst]
        return cands[0]["id"] if len(cands) == 1 else None

    node_by_key = {(n["path"], n["qualname"], n["line"]): n for n in nodes}
    edges: list[dict] = []
    for fr in file_results:
        for fn in fr["functions"]:
            caller = node_by_key[(fr["path"], fn["qualname"], fn["line"])]
            for call in fn["calls"]:
                edges.append(
                    {
                        "from": caller["id"],
                        "to": call["name"],
                        "resolved": call["resolved"],
                        "to_node": resolve(caller, call),
                        "kind": call["kind"],
                        "line": call["line"],
                    }
                )
    return {"nodes": nodes, "edges": edges}
