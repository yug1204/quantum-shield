"""Lightweight Java parser (standard library only).

It masks comments and string contents, matches braces, then finds types, methods and calls.
Good enough for crypto-call discovery (e.g. MessageDigest.getInstance("SHA-1")) and a call
graph. It is NOT a full Java grammar: when Tree-sitter is available in the team's
environment it can replace this module behind the same `parse_java(source, path)` function.
"""
from __future__ import annotations

import re
from bisect import bisect_right

from .python_parser import MAX_LITERAL_LEN, empty_result

KEYWORDS = {
    "if", "for", "while", "switch", "catch", "synchronized", "return", "throw", "assert",
    "else", "do", "try", "new", "super", "this", "case", "finally", "instanceof", "default",
}
SKIP_AFTER_PAREN = {"throws", "implements", "extends", "permits"}

TYPE_RE = re.compile(r"\b(class|interface|enum|record)\s+([A-Za-z_$][\w$]*)")
CALL_RE = re.compile(r"((?:[A-Za-z_$][\w$]*\s*\.\s*)*[A-Za-z_$][\w$]*)\s*\(")
NEW_RE = re.compile(r"\bnew\s+([A-Za-z_$][\w$.]*)\s*(?:<[^()]*>)?\s*\(")
IMPORT_RE = re.compile(r"^[ \t]*import\s+(static\s+)?([\w.$]+?)(\.\*)?\s*;", re.M)
PACKAGE_RE = re.compile(r"^[ \t]*package\s+([\w.]+)\s*;", re.M)
STR_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"$', re.S)
INT_RE = re.compile(r"^-?\d+[lL]?$")


# ---------------------------------------------------------------- masking
def _mask(src: str) -> str:
    """Same length as src: comments -> spaces, string/char contents -> '_' (newlines kept)."""
    out = list(src)
    n = len(src)

    def blank(a: int, b: int, ch: str) -> None:
        for k in range(a, min(b, n)):
            if out[k] not in "\r\n":
                out[k] = ch

    i = 0
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            blank(i, j, " ")
            i = j
        elif c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j, " ")
            i = j
        elif src.startswith('"""', i):
            j = src.find('"""', i + 3)
            j = n if j == -1 else j + 3
            blank(i + 3, max(i + 3, j - 3), "_")
            i = j
        elif c == '"' or c == "'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            blank(i + 1, j, "_")
            i = min(j + 1, n)
        else:
            i += 1
    return "".join(out)


def _braces(masked: str) -> tuple[list[int], dict[int, int]]:
    """depth[i] = number of unclosed '{' before index i; pairs[open_idx] = close_idx."""
    n = len(masked)
    depth = [0] * (n + 1)
    pairs: dict[int, int] = {}
    stack: list[int] = []
    d = 0
    for i, ch in enumerate(masked):
        depth[i] = d
        if ch == "{":
            stack.append(i)
            d += 1
        elif ch == "}":
            if stack:
                pairs[stack.pop()] = i
            d = max(0, d - 1)
    depth[n] = d
    return depth, pairs


def _match_paren(masked: str, open_idx: int, limit: int = 20000) -> int:
    d = 0
    end = min(len(masked), open_idx + limit)
    for i in range(open_idx, end):
        ch = masked[i]
        if ch == "(":
            d += 1
        elif ch == ")":
            d -= 1
            if d == 0:
                return i
    return -1


def _split_top(text: str, track_angle: bool) -> list[tuple[int, int]]:
    """Split on top-level commas. Returns (start, end) offsets into text."""
    parts: list[tuple[int, int]] = []
    d = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "([{" or (track_angle and ch == "<"):
            d += 1
        elif ch in ")]}" or (track_angle and ch == ">"):
            d = max(0, d - 1)
        elif ch == "," and d == 0:
            parts.append((start, i))
            start = i + 1
    parts.append((start, len(text)))
    if len(parts) == 1 and not text.strip():
        return []
    return parts


def _literal(text: str):
    t = text.strip()
    m = STR_RE.match(t)
    if m:
        return m.group(1)[:MAX_LITERAL_LEN]
    if INT_RE.match(t):
        return int(t.rstrip("lL"))
    return None


def _prev_char(masked: str, idx: int) -> str:
    j = idx - 1
    while j >= 0 and masked[j].isspace():
        j -= 1
    return masked[j] if j >= 0 else ""


def _prev_word(masked: str, idx: int) -> str:
    j = idx - 1
    while j >= 0 and masked[j].isspace():
        j -= 1
    k = j
    while k >= 0 and (masked[k].isalnum() or masked[k] in "_$"):
        k -= 1
    return masked[k + 1 : j + 1]


def _next_word(masked: str, idx: int) -> tuple[str, str]:
    """(next non-space char, next word) starting at idx."""
    j = idx
    n = len(masked)
    while j < n and masked[j].isspace():
        j += 1
    ch = masked[j] if j < n else ""
    k = j
    while k < n and (masked[k].isalnum() or masked[k] in "_$"):
        k += 1
    return ch, masked[j:k]


def _clean_bases(text: str) -> list[str]:
    prev = None
    while prev != text:  # strip nested generics
        prev = text
        text = re.sub(r"<[^<>]*>", "", text)
    return [t.strip() for t in text.split(",") if t.strip()]


# ---------------------------------------------------------------- main
def parse_java(source: str, path: str) -> dict:
    result = empty_result(path, "java", "java-light")
    try:
        _parse(source, result)
    except Exception as e:  # never let one odd file break a whole project scan
        result["errors"].append(f"{type(e).__name__}: {e}")
    return result


def _parse(src: str, result: dict) -> None:
    masked = _mask(src)
    n = len(src)
    line_starts = [0] + [m.end() for m in re.finditer("\n", src)]

    def line_of(off: int) -> int:
        return bisect_right(line_starts, off)

    depth, pairs = _braces(masked)

    # package + imports
    pm = PACKAGE_RE.search(masked)
    if pm:
        result["package"] = pm.group(1)
    aliases: dict[str, str] = {}
    for m in IMPORT_RE.finditer(masked):
        static, fqn, wildcard = bool(m.group(1)), m.group(2), bool(m.group(3))
        result["imports"].append(
            {"module": fqn, "static": static, "wildcard": wildcard, "names": [], "alias": None,
             "line": line_of(m.start())}
        )
        if not wildcard:
            aliases[fqn.split(".")[-1]] = fqn

    def resolve(name: str) -> str:
        first, _, rest = name.partition(".")
        first = first.strip()
        rest = re.sub(r"\s+", "", rest)
        if first in aliases:
            return aliases[first] + (f".{rest}" if rest else "")
        return re.sub(r"\s+", "", name)

    # ---- types
    types: list[dict] = []
    for m in TYPE_RE.finditer(masked):
        if _prev_char(masked, m.start()) == ".":
            continue
        j, pd, body_open = m.end(), 0, -1
        while j < n:
            ch = masked[j]
            if ch == "(":
                pd += 1
            elif ch == ")":
                pd -= 1
            elif ch == ";" and pd <= 0:
                break
            elif ch == "{" and pd <= 0:
                body_open = j
                break
            j += 1
        if body_open == -1 or body_open not in pairs:
            continue
        header = re.sub(r"\s+", " ", masked[m.end() : body_open])
        bases: list[str] = []
        em = re.search(r"\bextends\s+(.+?)(?=\s+implements\b|\s+permits\b|$)", header)
        im = re.search(r"\bimplements\s+(.+?)(?=\s+permits\b|$)", header)
        for g in (em, im):
            if g:
                bases += _clean_bases(g.group(1))
        types.append(
            {"name": m.group(2), "kind": m.group(1), "open": body_open, "close": pairs[body_open],
             "start": m.start(), "bases": bases}
        )
    types.sort(key=lambda t: t["open"])
    for t in types:
        enclosing = [o for o in types if o["open"] < t["open"] < o["close"]]
        parent = max(enclosing, key=lambda o: o["open"]) if enclosing else None
        t["qualname"] = f"{parent['qualname']}.{t['name']}" if parent else t["name"]
        result["classes"].append(
            {"name": t["name"], "qualname": t["qualname"], "kind": t["kind"],
             "line": line_of(t["start"]), "end_line": line_of(t["close"]), "bases": t["bases"]}
        )

    # ---- methods
    methods: list[dict] = []
    decl_offsets: set[int] = set()
    used_ids: dict[str, int] = {}
    for t in types:
        body_depth = depth[t["open"]] + 1
        for m in re.finditer(r"([A-Za-z_$][\w$]*)\s*\(", masked[t["open"] + 1 : t["close"]]):
            name_off = t["open"] + 1 + m.start(1)
            if depth[name_off] != body_depth:
                continue
            name = m.group(1)
            if name in KEYWORDS:
                continue
            pc = _prev_char(masked, name_off)
            if not (pc.isalnum() or pc in "_$>];}){" or pc == ""):
                continue  # '.', '=', '@', ',', '(' ... => call/annotation/initializer, not a declaration
            if _prev_word(masked, name_off) in ("new", "return", "throw", "else", "case"):
                continue
            popen = t["open"] + 1 + m.end() - 1
            pclose = _match_paren(masked, popen)
            if pclose == -1:
                continue
            j = pclose + 1
            # optional "throws A, B" / "default value"
            ch, word = _next_word(masked, j)
            if word == "throws":
                k = j
                while k < n and masked[k] not in "{;":
                    k += 1
                j = k
            ch, _ = _next_word(masked, j)
            if ch == "{":
                bopen = masked.index("{", j)
                bclose = pairs.get(bopen, -1)
                if bclose == -1:
                    continue
                abstract = False
            elif ch == ";":
                bopen = bclose = -1
                abstract = True
            else:
                continue
            params = []
            for a, b in _split_top(src[popen + 1 : pclose], track_angle=True):
                words = re.findall(r"[A-Za-z_$][\w$]*", masked[popen + 1 + a : popen + 1 + b])
                if words:
                    params.append(words[-1])
            qual = f"{t['qualname']}.{name}"
            cnt = used_ids.get(qual, 0) + 1
            used_ids[qual] = cnt
            methods.append(
                {"id": qual if cnt == 1 else f"{qual}#{cnt}", "qualname": qual, "name": name,
                 "class": t["qualname"], "kind": "constructor" if name == t["name"] else "method",
                 "line": line_of(name_off), "end_line": line_of(bclose if bclose != -1 else pclose),
                 "params": params, "abstract": abstract, "async": False, "calls": [],
                 "_open": bopen, "_close": bclose}
            )
            decl_offsets.add(name_off)

    # ---- calls
    def make_call(name: str, kind: str, name_off: int, popen: int) -> dict | None:
        pclose = _match_paren(masked, popen)
        if pclose == -1:
            return None
        args = []
        inner = masked[popen + 1 : pclose]
        for a, b in _split_top(inner, track_angle=False):
            args.append(_literal(src[popen + 1 + a : popen + 1 + b]))
        clean = re.sub(r"\s+", "", name)
        return {"name": clean, "resolved": resolve(name), "kind": kind, "line": line_of(name_off),
                "args": args, "kwargs": {}, "_off": name_off}

    found: list[dict] = []
    new_offsets: set[int] = set()
    for m in NEW_RE.finditer(masked):
        c = make_call(m.group(1), "new", m.start(1), m.end() - 1)
        if c:
            found.append(c)
            new_offsets.add(m.start(1))
    for m in CALL_RE.finditer(masked):
        off = m.start(1)
        if off in decl_offsets or off in new_offsets:
            continue
        name = m.group(1)
        last = re.split(r"\s*\.\s*", name)[-1]
        if last in KEYWORDS or name in KEYWORDS:
            continue
        if _prev_char(masked, off) == "@":
            continue
        if _prev_word(masked, off) == "new":
            continue
        popen = m.end() - 1
        pclose = _match_paren(masked, popen)
        if pclose == -1:
            continue
        ch, word = _next_word(masked, pclose + 1)
        if ch == "{" or word in SKIP_AFTER_PAREN:
            continue  # declaration (anonymous-class method, record header, ...)
        c = make_call(name, "call", off, popen)
        if c:
            found.append(c)

    found.sort(key=lambda c: c["_off"])
    for c in found:
        off = c.pop("_off")
        owners = [m for m in methods if m["_open"] != -1 and m["_open"] < off < m["_close"]]
        if owners:
            min(owners, key=lambda m: m["_close"] - m["_open"])["calls"].append(c)
        else:
            result["module_calls"].append(c)

    for m in methods:
        m.pop("_open")
        m.pop("_close")
    result["functions"] = methods
