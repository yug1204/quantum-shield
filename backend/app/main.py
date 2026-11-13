from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import ingest


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.repos_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)  # swap for Alembic once schema stabilises
    yield


app = FastAPI(title="Quantum Shield API", version="0.1.0", lifespan=lifespan)

# Shivam's React dev server (Vite default port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(ingest.router)