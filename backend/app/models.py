"""DB tables for Phase 1. Matches the 'Database Design' box in the roadmap
(Projects -> Repositories -> Files). Later phases add Nodes/Edges/Vulnerabilities/RiskScores.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    repositories: Mapped[list["Repository"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source: Mapped[str] = mapped_column(String(500))          # github url or "upload:<name>"
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_path: Mapped[str] = mapped_column(String(500))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="repositories")
    files: Mapped[list["File"]] = relationship(back_populates="repository", cascade="all, delete-orphan")


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    language: Mapped[str] = mapped_column(String(30), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    line_count: Mapped[int] = mapped_column(Integer)
    crypto_hints: Mapped[list] = mapped_column(JSON, default=list)

    repository: Mapped[Repository] = relationship(back_populates="files")
