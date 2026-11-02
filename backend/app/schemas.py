from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GithubIngestRequest(BaseModel):
    repo_url: str = Field(examples=["https://github.com/pallets/flask"])
    branch: str | None = None
    project_name: str | None = None


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    language: str
    kind: str
    size_bytes: int
    sha256: str
    line_count: int
    crypto_hints: list[str]


class RepositoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    source: str
    branch: str | None
    commit_sha: str | None
    summary: dict
    created_at: datetime


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    repositories: list[RepositoryOut] = []
