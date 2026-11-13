"""Week 2 tests: Python parser, Java parser, call graph, project runner. Standard library only.
Run: pytest tests/test_parsers.py
"""
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.services.file_filter import scan_directory  # noqa: E402
from parsers import build_call_graph, parse_java, parse_project, parse_python  # noqa: E402

SAMPLE = ROOT / "sample_vulnerable_repo"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def by_id(result):
    return {f["id"]: f for f in result["functions"]}


# ------------------------------------------------------------------ python
PY_SRC = '''
import hashlib
import os.path
from Crypto.PublicKey import RSA as R
from . import local_mod

KEY = R.generate(1024)

def make_keys():
    return R.generate(2048)

@decorator("x")
class Auth(Base):
    def hash(self, pw, *args, salt=None, **kw):
        return hashlib.md5(pw.encode()).hexdigest()

    async def login(self, pw):
        self.hash(pw)
        def inner():
            os.path.join("a")
        inner()
        hashlib.new("sha1", b"x")

def make_keys():   # redefinition gets a unique id
    pass
'''


def test_python_structure():
    r = parse_python(PY_SRC, "a.py")
    assert r["errors"] == []
    funcs = by_id(r)
    assert set(funcs) == {"make_keys", "make_keys#2", "Auth.hash", "Auth.login", "Auth.login.inner"}
    assert funcs["Auth.hash"]["class"] == "Auth"
    assert funcs["Auth.hash"]["params"] == ["self", "pw", "*args", "salt", "**kw"]
    assert funcs["Auth.login"]["async"] is True
    assert funcs["Auth.login.inner"]["class"] is None
    assert [c["name"] for c in r["classes"]] == ["Auth"]
    assert r["classes"][0]["bases"] == ["Base"]
    assert {i["module"] for i in r["imports"]} >= {"hashlib", "os.path", "Crypto.PublicKey", "."}


def test_python_calls_resolution_and_literals():
    r = parse_python(PY_SRC, "a.py")
    funcs = by_id(r)
    gen = funcs["make_keys"]["calls"][0]
    assert gen["name"] == "R.generate"
    assert gen["resolved"] == "Crypto.PublicKey.RSA.generate"
    assert gen["args"] == [2048]

    # module-level call (key size 1024) and decorator call belong to module scope
    mod_names = [c["name"] for c in r["module_calls"]]
    assert "R.generate" in mod_names and "decorator" in mod_names

    md5 = [c for c in funcs["Auth.hash"]["calls"] if c["name"] == "hashlib.md5"][0]
    assert md5["resolved"] == "hashlib.md5" and md5["args"] == [None]

    login_calls = {c["name"]: c for c in funcs["Auth.login"]["calls"]}
    assert "self.hash" in login_calls and "inner" in login_calls
    assert "os.path.join" not in login_calls                     # belongs to nested function
    assert funcs["Auth.login.inner"]["calls"][0]["resolved"] == "os.path.join"
    assert login_calls["hashlib.new"]["args"] == ["sha1", None]


def test_python_syntax_error_does_not_raise():
    r = parse_python("def broken(:\n  pass", "bad.py")
    assert r["functions"] == [] and "SyntaxError" in r["errors"][0]


# ------------------------------------------------------------------ java
def test_java_fixture():
    r = parse_java((FIXTURES / "Signer.java").read_text(), "Signer.java")
    assert r["errors"] == [] and r["package"] == "com.acme.sec"
    assert [(c["qualname"], c["kind"]) for c in r["classes"]] == [
        ("Signer", "class"), ("Signer.Inner", "class"), ("Shape", "interface")]
    assert r["classes"][0]["bases"] == ["Object", "Runnable"]

    funcs = by_id(r)
    assert set(funcs) == {
        "Signer.compute", "Signer.Signer", "Signer.init", "Signer.run",
        "Signer.helper", "Signer.todo", "Signer.Inner.go", "Shape.area"}
    assert funcs["Signer.Signer"]["kind"] == "constructor"
    assert funcs["Signer.helper"]["params"] == ["a", "b"]          # generics/final handled
    assert funcs["Signer.todo"]["abstract"] and funcs["Shape.area"]["abstract"]

    run = {(c["kind"], c["name"]): c for c in funcs["Signer.run"]["calls"]}
    assert run[("call", "KeyPairGenerator.getInstance")]["args"] == ["RSA"]
    assert run[("call", "KeyPairGenerator.getInstance")]["resolved"] == "java.security.KeyPairGenerator.getInstance"
    assert run[("call", "kpg.initialize")]["args"] == [2048]
    assert run[("call", "MessageDigest.getInstance")]["args"] == ["SHA-1"]
    assert run[("call", "max")]["resolved"] == "java.lang.Math.max"      # static import
    assert ("new", "java.util.ArrayList") in run and ("new", "Runnable") in run
    assert ("call", "init") in run                                       # inside anonymous class -> enclosing method
    assert ("call", "foo") not in run                                    # inside a string literal


def test_java_ignores_braces_in_strings_chars_comments():
    src = '''
class A {
    char c = '{'; String s = "}}}"; // {{{
    /* } */
    void f() { g("{"); }
    void h() { f(); }
}
'''
    r = parse_java(src, "A.java")
    funcs = by_id(r)
    assert set(funcs) == {"A.f", "A.h"}
    assert [c["name"] for c in funcs["A.f"]["calls"]] == ["g"]
    assert [c["name"] for c in funcs["A.h"]["calls"]] == ["f"]


def test_java_overloads_get_unique_ids_and_never_raises():
    r = parse_java("class B { void f(int a){} void f(String a){} }", "B.java")
    assert set(by_id(r)) == {"B.f", "B.f#2"}
    broken = parse_java("class { void ( ( { ", "X.java")      # garbage in, no exception out
    assert isinstance(broken["errors"], list)


# ------------------------------------------------------------------ graph
def test_call_graph_resolution():
    src = '''
import hashlib
class S:
    def a(self): self.b(); helper(); hashlib.md5(b"x"); S.c()
    def b(self): pass
    @staticmethod
    def c(): pass
def helper(): pass
'''
    g = build_call_graph([parse_python(src, "m.py")])
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"m.py::S.a", "m.py::S.b", "m.py::S.c", "m.py::helper"}
    edges = {e["to"]: e for e in g["edges"] if e["from"] == "m.py::S.a"}
    assert edges["self.b"]["to_node"] == "m.py::S.b"
    assert edges["helper"]["to_node"] == "m.py::helper"
    assert edges["S.c"]["to_node"] == "m.py::S.c"
    assert edges["hashlib.md5"]["to_node"] is None        # library call stays unresolved


# ------------------------------------------------------------------ project
def test_parse_sample_repo():
    files = [asdict(f) for f in scan_directory(SAMPLE)]
    res = parse_project(SAMPLE, files)
    s = res["summary"]
    assert s["files_parsed"] == 2 and s["files_with_errors"] == 0
    assert s["skipped_unsupported_language"] == {"c": 1}
    by_path = {f["path"]: f for f in res["files"]}

    py = by_id(by_path["src/auth.py"])
    assert py["make_keys"]["calls"][0]["resolved"] == "Crypto.PublicKey.RSA.generate"
    assert py["make_keys"]["calls"][0]["args"] == [2048]
    assert "hashlib.md5" in [c["resolved"] for c in py["hash_password"]["calls"]]

    java = by_id(by_path["src/Signer.java"])["Signer.sign"]
    got = {(c["resolved"], tuple(c["args"])) for c in java["calls"] if c["args"]}
    assert ("java.security.KeyPairGenerator.getInstance", ("EC",)) in got
    assert ("java.security.Signature.getInstance", ("SHA256withECDSA",)) in got
    assert ("java.security.MessageDigest.getInstance", ("SHA-1",)) in got


def test_parse_project_blocks_path_escape(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "secret.py").write_text("def leak(): pass\n")
    res = parse_project(tmp_path / "proj", [{"path": "../secret.py", "language": "python", "kind": "source"}])
    assert res["files"][0]["functions"] == []
    assert "outside" in res["files"][0]["errors"][0]
