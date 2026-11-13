"""Phase 2 endpoint: POST /projects/{id}/parse -> AST summary + call graph for an ingested project."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from parsers import parse_project

from ..db import get_db
from ..models import Project

router = APIRouter()


@router.post("/projects/{project_id}/parse")
def parse_project_endpoint(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    results = []
    for repo in project.repositories:
        root = Path(repo.local_path)
        if not root.is_dir():
            raise HTTPException(status_code=410, detail="Source files are no longer on the server. Ingest the project again.")
        files = [{"path": f.path, "language": f.language, "kind": f.kind} for f in repo.files]
        results.append({"repository_id": repo.id, **parse_project(root, files)})
    return {"project_id": project_id, "repositories": results}
