"""Phase 1 endpoints: POST /github, POST /upload, GET /projects, GET /projects/{id}, GET /projects/{id}/files"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File as FormFile, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import File, Project, Repository
from ..schemas import FileOut, GithubIngestRequest, ProjectOut, RepositoryOut
from ..services.git_service import IngestionError, parse_github_url
from ..services.ingestion import ingest_github, ingest_zip

router = APIRouter()


def _save(db: Session, project_name: str, result: dict, branch: str | None) -> Repository:
    project = Project(name=project_name)
    repo = Repository(
        project=project,
        source=result["source"],
        branch=branch,
        commit_sha=result["commit"],
        local_path=result["local_path"],
        summary=result["summary"],
    )
    repo.files = [File(**f) for f in result["files"]]
    db.add(project)
    db.commit()
    return repo


@router.post("/github", response_model=RepositoryOut, status_code=201)
def ingest_from_github(body: GithubIngestRequest, db: Session = Depends(get_db)):
    try:
        owner, name = parse_github_url(body.repo_url)
        result = ingest_github(body.repo_url, settings.repos_dir, body.branch)
    except IngestionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _save(db, body.project_name or f"{owner}/{name}", result, body.branch)


@router.post("/upload", response_model=RepositoryOut, status_code=201)
async def ingest_from_zip(
    file: UploadFile = FormFile(...),
    project_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip file.")
    limit = settings.max_upload_mb * 1024 * 1024
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "upload.zip"
        size = 0
        with zpath.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail="Upload too large.")
                out.write(chunk)
        try:
            result = ingest_zip(zpath, settings.repos_dir, Path(file.filename).stem)
        except IngestionError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return _save(db, project_name or Path(file.filename).stem, result, None)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.scalars(select(Project).order_by(Project.id.desc())).all()


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@router.get("/projects/{project_id}/files", response_model=list[FileOut])
def list_files(
    project_id: int,
    language: str | None = None,
    crypto_only: bool = False,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    q = select(File).join(Repository).where(Repository.project_id == project_id)
    if language:
        q = q.where(File.language == language)
    files = db.scalars(q.order_by(File.path)).all()
    if crypto_only:
        files = [f for f in files if f.crypto_hints]
    return files
