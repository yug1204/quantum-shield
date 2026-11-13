# Quantum Shield - Week 1-2 (Phase 1: Ingestion, Phase 2: Parser + Call Graph)

Repo URL do -> code clone hoga -> relevant files filter hongi -> metadata DB mein save hoga.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest -q                                   # core + API tests
uvicorn backend.app.main:app --reload       # http://localhost:8000/docs
```

Docker (FastAPI + PostgreSQL + Redis): `docker compose up --build`

## Endpoints (Week 1)

| Method | Path | Kaam |
|---|---|---|
| POST | `/github` | `{"repo_url": "https://github.com/owner/repo", "branch": "main"}` -> clone + scan + DB |
| POST | `/upload` | `.zip` upload -> extract + scan + DB |
| GET | `/projects` | saare projects |
| GET | `/projects/{id}` | ek project + repos |
| GET | `/projects/{id}/files?language=python&crypto_only=true` | files list |
| POST | `/projects/{id}/parse` | (Week 2) AST summary + call graph for an ingested project |
| GET | `/health` | health check |

Try: `curl -X POST localhost:8000/github -H 'content-type: application/json' -d '{"repo_url":"https://github.com/<owner>/<repo>"}'`

## Week 2: parser + call graph

```bash
python -m parsers.cli sample_vulnerable_repo              # prints a summary
python -m parsers.cli path/to/code --out result.json      # full JSON
```
- Python: standard-library `ast` (exact). Java: lightweight parser (comments/strings masked, braces matched). C/C++/JS/TS are skipped for now and counted in `skipped_unsupported_language`.
- Every function lists its calls with `resolved` names (imports expanded, e.g. `java.security.MessageDigest.getInstance`) and literal args (`["SHA-1"]`, `[2048]`) - this is what the Phase 3 crypto detector reads.
- Output contract: `schemas/parse_output.schema.json`.
- Known limits: call-graph edges are name based (library calls stay unresolved on purpose); Java parser is not a full grammar - swap in Tree-sitter later behind `parse_java(source, path)`.

## Folder layout

```
backend/app/services/   file_filter.py  git_service.py  ingestion.py   <- core logic (stdlib only)
backend/app/routers/    ingest.py                                       <- FastAPI endpoints
backend/app/            models.py db.py schemas.py config.py main.py
schemas/                ingestion_output.schema.json (Sahil -> Ritesh), parse_output.schema.json (Ritesh -> Shree)
sample_vulnerable_repo/ test fixture with weak crypto
parsers/                python_parser.py java_parser.py graph.py project.py cli.py   <- Week 2
ai/ risk/ refactor/ frontend/   <- baaki team ke folders (Week 3+)
```

## Safety built in
- Sirf `https://github.com/owner/repo` URLs allowed (no file://, no other hosts)
- Shallow clone (`--depth 1`), 120s timeout, git hooks disabled, no credential prompts
- Cloned code kabhi execute nahi hota, sirf padha jaata hai
- Zip-slip + zip-bomb protection, symlinks skip, 1 MB/file limit
- `node_modules`, `.git`, `venv`, `build` etc. skip

## Team handoff (Week 2)
- **Ritesh:** `schemas/ingestion_output.schema.json` padho. `files[].path` under `local_path` -> Tree-sitter se parse karo.
- **Shree:** `crypto_hints` sirf quick keyword hint hai, asli detection Phase 3 mein tumhara kaam hai.
- **Shivam:** frontend `/projects` aur `/projects/{id}/files` consume kare. CORS `localhost:5173` ke liye on hai.

## Week 1 checklist
- [x] Monorepo structure
- [x] FastAPI + `/github` + `/upload` + `/projects`
- [x] File filter + language detect + SHA256 + line count + crypto hints
- [x] DB models (Project / Repository / File)
- [x] Docker compose, CI, tests
- [ ] Real GitHub repo pe live test (apni machine pe karna hai)
- [ ] Alembic migrations (jab schema stable ho jaaye)
