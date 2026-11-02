"""Tests for the framework-free core (file filter, git service, ingestion).
Run: pytest tests/test_core.py
"""
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.services.file_filter import classify, scan_directory, summarize  # noqa: E402
from backend.app.services.git_service import (  # noqa: E402
    IngestionError,
    clone_repo,
    extract_zip,
    parse_github_url,
)
from backend.app.services.ingestion import ingest_github, ingest_zip  # noqa: E402

SAMPLE = ROOT / "sample_vulnerable_repo"


@pytest.fixture()
def sample_git_repo(tmp_path: Path) -> Path:
    """Copy the sample fixture into a real local git repo so we can test cloning offline."""
    import shutil

    dst = tmp_path / "src_repo"
    shutil.copytree(SAMPLE, dst)
    (dst / "node_modules").mkdir()
    (dst / "node_modules" / "junk.js").write_text("var RSA = 1;")
    run = lambda *a: subprocess.run(["git", *a], cwd=dst, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    run("add", ".")
    run("commit", "-q", "-m", "init")
    return dst


# ---------- URL validation ----------
@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/pallets/flask",
        "https://github.com/pallets/flask.git",
        "https://github.com/a-b/c_d.e/",
    ],
)
def test_valid_github_urls(url):
    owner, repo = parse_github_url(url)
    assert owner and repo


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://evil.com/a/b",
        "https://github.com/a/b; rm -rf /",
        "file:///etc/passwd",
        "--upload-pack=touch /tmp/x",
        "https://github.com/a",
    ],
)
def test_invalid_github_urls(url):
    with pytest.raises(IngestionError):
        parse_github_url(url)


def test_bad_branch_rejected(tmp_path):
    with pytest.raises(IngestionError):
        clone_repo("https://github.com/a/b", tmp_path, branch="--evil; x")


# ---------- classify ----------
def test_classify():
    assert classify(Path("a.py")) == ("python", "source")
    assert classify(Path("A.JAVA")) == ("java", "source")
    assert classify(Path("x.cpp")) == ("cpp", "source")
    assert classify(Path("cert.pem"))[1] == "certificate"
    assert classify(Path("notes.txt")) is None
    assert classify(Path("img.png")) is None


# ---------- scan ----------
def test_scan_sample_repo():
    files = scan_directory(SAMPLE)
    paths = {f.path: f for f in files}
    assert "src/auth.py" in paths
    assert "src/Signer.java" in paths
    assert "src/crypto_utils.c" in paths
    assert "config.yaml" in paths
    assert "README.md" not in paths

    assert {"RSA", "MD5"} <= set(paths["src/auth.py"].crypto_hints)
    assert {"ECDSA", "SHA1"} <= set(paths["src/Signer.java"].crypto_hints)
    assert {"RSA", "MD5"} <= set(paths["src/crypto_utils.c"].crypto_hints)
    assert "DES" in paths["config.yaml"].crypto_hints

    s = summarize(files)
    assert s["by_language"]["python"] == 1
    assert s["by_language"]["java"] == 1
    assert s["files_with_crypto_hints"] == 4


def test_scan_skips_dirs_symlinks_and_big_files(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("RSA")
    (tmp_path / "ok.py").write_text("print(1)\n")
    (tmp_path / "big.py").write_bytes(b"#" * 1_100_000)
    (tmp_path / "link.py").symlink_to(tmp_path / "ok.py")
    paths = [f.path for f in scan_directory(tmp_path)]
    assert paths == ["ok.py"]


def test_scan_line_count_and_hash(tmp_path):
    (tmp_path / "a.py").write_text("a\nb\nc")
    f = scan_directory(tmp_path)[0]
    assert f.line_count == 3
    assert len(f.sha256) == 64


# ---------- clone ----------
def test_clone_local_repo(sample_git_repo, tmp_path):
    dest, sha = clone_repo(str(sample_git_repo), tmp_path / "out", allow_local=True)
    assert (dest / "src" / "auth.py").exists()
    assert len(sha) == 40


def test_ingest_end_to_end(sample_git_repo, tmp_path):
    result = ingest_github(str(sample_git_repo), tmp_path / "out", allow_local=True)
    assert result["schema_version"] == "1.0"
    assert len(result["commit"]) == 40
    paths = {f["path"] for f in result["files"]}
    assert "src/auth.py" in paths
    assert not any(p.startswith("node_modules") for p in paths)
    assert result["summary"]["files_with_crypto_hints"] == 4


def test_local_path_rejected_without_flag(sample_git_repo, tmp_path):
    with pytest.raises(IngestionError):
        clone_repo(str(sample_git_repo), tmp_path / "out")


# ---------- zip ----------
def test_zip_upload(tmp_path):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(SAMPLE / "src" / "auth.py", "proj/auth.py")
    result = ingest_zip(z, tmp_path / "out", "p")
    assert [f["path"] for f in result["files"]] == ["proj/auth.py"]


def test_zip_slip_blocked(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../evil.py", "x")
    with pytest.raises(IngestionError):
        extract_zip(z, tmp_path / "out")
    assert not (tmp_path / "evil.py").exists()


def test_bad_zip(tmp_path):
    z = tmp_path / "bad.zip"
    z.write_text("not a zip")
    with pytest.raises(IngestionError):
        extract_zip(z, tmp_path / "out")
