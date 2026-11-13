"""Python source -> structured summary, using the standard library `ast` module.

Output (per file):
  imports, classes, functions (each with its calls), module_calls, errors
Every call carries `name` (as written, e.g. "R.generate"), `resolved` (import aliases
expanded, e.g. "Crypto.PublicKey.RSA.generate"), the line, and literal arguments
(e.g. [2048]) because key sizes and algorithm names matter for crypto analysis.
"""
from __future__ import annotations

import ast

MAX_LITERAL_LEN = 120


def empty_result(path: str, language: str, parser: str) -> dict:
    return {
        "path": path,
        "language": language,
        "parser": parser,
        "imports": [],
        "classes": [],
        "functions": [],
        "module_calls": [],
        "errors": [],
    }


def _lit(node: ast.AST):
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool) or v is None:
            return None
        if isinstance(v, str):
            return v[:MAX_LITERAL_LEN]
        if isinstance(v, (int, float)):
            return v
    return None


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return f"{_dotted(node.func)}()"
    if isinstance(node, ast.Subscript):
        return f"{_dotted(node.value)}[]"
    return "?"


def _collect_aliases(tree: ast.AST) -> dict[str, str]:
    """alias -> fully qualified name, from every import in the file (also those inside functions)."""
    aliases: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    aliases[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(n, ast.ImportFrom):
            mod = "." * n.level + (n.module or "")
            for a in n.names:
                if a.name == "*":
                    continue
                full = f"{mod}{a.name}" if (not mod or mod.endswith(".")) else f"{mod}.{a.name}"
                aliases[a.asname or a.name] = full
    return aliases


class _Visitor(ast.NodeVisitor):
    def __init__(self, result: dict, aliases: dict[str, str]):
        self.r = result
        self.aliases = aliases
        self.scope: list[tuple[str, str]] = []   # ("class"|"func", name)
        self.func_stack: list[dict] = []
        self.used_ids: dict[str, int] = {}

    # ---- helpers
    def _qual(self, name: str) -> str:
        return ".".join([s[1] for s in self.scope] + [name])

    def _unique_id(self, qual: str) -> str:
        n = self.used_ids.get(qual, 0) + 1
        self.used_ids[qual] = n
        return qual if n == 1 else f"{qual}#{n}"

    def _calls(self) -> list:
        return self.func_stack[-1]["calls"] if self.func_stack else self.r["module_calls"]

    def _resolve(self, name: str) -> str:
        first, _, rest = name.partition(".")
        if first in self.aliases:
            return self.aliases[first] + (f".{rest}" if rest else "")
        return name

    # ---- imports
    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.r["imports"].append({"module": a.name, "alias": a.asname, "names": [], "line": node.lineno})

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = "." * node.level + (node.module or "")
        self.r["imports"].append(
            {"module": mod, "alias": None, "names": [a.name for a in node.names], "line": node.lineno}
        )

    # ---- definitions
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for d in node.decorator_list:
            self.visit(d)
        for b in node.bases:
            self.visit(b)
        for k in node.keywords:
            self.visit(k.value)
        qual = self._qual(node.name)
        self.r["classes"].append(
            {
                "name": node.name,
                "qualname": qual,
                "kind": "class",
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "bases": [_dotted(b) for b in node.bases],
            }
        )
        self.scope.append(("class", node.name))
        for stmt in node.body:
            self.visit(stmt)
        self.scope.pop()

    def _function(self, node, is_async: bool) -> None:
        for d in node.decorator_list:
            self.visit(d)
        a = node.args
        for dflt in list(a.defaults) + [x for x in a.kw_defaults if x is not None]:
            self.visit(dflt)
        qual = self._qual(node.name)
        parent_class = self.scope[-1][1] if self.scope and self.scope[-1][0] == "class" else None
        params = [x.arg for x in a.posonlyargs + a.args]
        if a.vararg:
            params.append("*" + a.vararg.arg)
        params += [x.arg for x in a.kwonlyargs]
        if a.kwarg:
            params.append("**" + a.kwarg.arg)
        entry = {
            "id": self._unique_id(qual),
            "qualname": qual,
            "name": node.name,
            "class": parent_class,
            "kind": "method" if parent_class else "function",
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "params": params,
            "async": is_async,
            "calls": [],
        }
        self.r["functions"].append(entry)
        self.scope.append(("func", node.name))
        self.func_stack.append(entry)
        for stmt in node.body:
            self.visit(stmt)
        self.func_stack.pop()
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, True)

    # ---- calls
    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted(node.func)
        kwargs = {}
        for k in node.keywords:
            v = _lit(k.value)
            if k.arg and v is not None:
                kwargs[k.arg] = v
        self._calls().append(
            {
                "name": name,
                "resolved": self._resolve(name),
                "kind": "call",
                "line": node.lineno,
                "args": [_lit(x) for x in node.args],
                "kwargs": kwargs,
            }
        )
        self.generic_visit(node)


def parse_python(source: str, path: str) -> dict:
    result = empty_result(path, "python", "python-ast")
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        result["errors"].append(f"SyntaxError line {e.lineno}: {e.msg}")
        return result
    except (ValueError, RecursionError, MemoryError) as e:
        result["errors"].append(f"{type(e).__name__}: {e}")
        return result

    _Visitor(result, _collect_aliases(tree)).visit(tree)
    for fn in result["functions"]:
        fn["calls"].sort(key=lambda c: c["line"])
    result["module_calls"].sort(key=lambda c: c["line"])
    return result
