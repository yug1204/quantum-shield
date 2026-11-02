"""API tests (need fastapi/sqlalchemy/httpx installed: pip install -r requirements.txt).
Run: pytest tests/test_api.py
NOTE: written but NOT yet executed - the build sandbox could not reach PyPI.
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.app import db as dbmod  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.main import app  # noqa: E402

SAMPLE = ROOT / "sample_vulnerable_repo"


@pytest.fixture()
def client(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    dbmod.Base.metadata.create_all(bind=engine)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[dbmod.get_db] = override
    settings.repos_dir = tmp_path / "repos"
    yield TestClient(app)
    app.dependency_overrides.clear()


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in SAMPLE.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(SAMPLE.parent).as_posix())
    return buf.getvalue()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_github_rejects_bad_url(client):
    r = client.post("/github", json={"repo_url": "https://evil.com/a/b"})
    assert r.status_code == 400


def test_upload_then_query(client):
    r = client.post("/upload", files={"file": ("sample.zip", _zip_bytes(), "application/zip")})
    assert r.status_code == 201, r.text
    pid = r.json()["project_id"]
    assert r.json()["summary"]["files_with_crypto_hints"] == 4

    assert len(client.get("/projects").json()) == 1
    files = client.get(f"/projects/{pid}/files").json()
    assert any(f["path"].endswith("auth.py") for f in files)
    assert all(f["language"] == "python" for f in client.get(f"/projects/{pid}/files?language=python").json())
    assert client.get("/projects/999").status_code == 404


def test_upload_rejects_non_zip(client):
    r = client.post("/upload", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400
