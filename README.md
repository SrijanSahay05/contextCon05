# contextCon05

- `backend/` — FastAPI, SQLAlchemy + Alembic (Postgres), PyMongo (MongoDB). Config in `backend/.env` (copy `backend/.env.example`).
- `frontend/` — Vite + React + TypeScript. Dev server proxies `/api/*` to the backend; in Docker, nginx serves the build and does the same.
- `docs/` — [`architecture.md`](docs/architecture.md) (tech stack and code architecture), PRDs, implementation plans, change logs.

Coding agents: see [`AGENTS.md`](AGENTS.md) (`CLAUDE.md` imports it).

## Run

```sh
make install     # backend deps (uv) + frontend deps (pnpm)
make dev         # backend + postgres + mongo in Docker
make front       # frontend dev server on :5173
make up          # full stack in Docker (frontend on :80)
make db-generate MESSAGE="add users"   # new Alembic revision
make db-migrate                        # apply revisions
```
