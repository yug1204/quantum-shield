from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import ingest

app = FastAPI(title="Quantum Shield API", version="0.1.0")

# Shivam's React dev server (Vite default port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    settings.repos_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)  # swap for Alembic once schema stabilises


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(ingest.router)
