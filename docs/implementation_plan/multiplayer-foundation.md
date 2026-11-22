# Implementation plan: async foundation → multiplayer → first flow

Written 22 Nov 2026, before work began. This is a historical plan; trust the code
over it once work lands. Product spec: `docs/prd/startup-workspace.md`.

Built by hand. KITH (`~/Developer/kith-v0`) is a reference for patterns only;
declare it under "Anything written before 10:15 AM" on the submission form.

Each phase ends in its own PR, from its own branch off an up-to-date `main`.
Each line under "Commits" is one Conventional Commit. Every phase ends with
`make check` green.

**Cut line for the 6:00 PM code freeze:** phases 0–5 plus the grants flow (6a)
are the demo. The other domains follow in the 6b order as stretch goals;
whatever isn't built goes in the README as "what comes next".

---

## Phase 0: async Postgres + Redis, drop Mongo

Branch: `refactor/async-db-redis`

**Goal:** the same `/healthz` app, now running on async SQLAlchemy + asyncpg and
Redis, with Mongo gone everywhere.

Commits:

1. `chore(backend): switch db driver to asyncpg and add redis`
   - `uv add asyncpg redis httpx`
   - `uv remove pymongo psycopg`
   - Async tests use the `anyio` pytest plugin, which is already installed with
     Starlette, so no pytest-asyncio.
   - httpx is needed as a runtime dependency for the Crustdata client in phase 5.
     The dev-only `httpx2` stays for `TestClient`.
2. `refactor(backend): async engine, session factory and get_db`
   - `app/db/session.py`:
     - `create_engine(settings)` → `create_async_engine(..., pool_pre_ping=True)`
     - `create_session_factory(engine)` → `async_sessionmaker(expire_on_commit=False)`
     - `get_db(request)` yields a session from `request.app.state.db_session_factory`.
       It commits on success and rolls back on error.
   - `app/main.py`: a `lifespan` creates the engine and session factory on
     `app.state` and disposes of the engine on shutdown. No engine is created at
     import time any more, so tests and alembic don't open connections when
     they import.
   - Config: `database_url` now uses `postgresql+asyncpg://`.
3. `feat(backend): redis client on app state`
   - `app/db/redis.py`: `create_redis_client(settings)`, which is
     `Redis.from_url(..., decode_responses=True)`.
   - `lifespan` opens it on startup and runs `aclose()` on shutdown.
   - `get_redis(request)` dependency.
   - New setting `redis_url`.
4. `refactor(backend): healthz pings postgres and redis`
   - `async def healthz`: runs `SELECT 1` and `await redis.ping()`.
   - `app/db/mongo.py` is deleted, along with the Mongo settings.
   - The test becomes "reaches both stores". It uses
     `with TestClient(app) as c:` so the lifespan runs.
5. `chore(infra): replace mongo with redis in compose, env and CI`
   - **Compose:** add a `redis:7-alpine` service with a healthcheck
     (`redis-cli ping`), on **host port 6380**, because 6379 is used by another
     project on this machine. The backend's environment overrides
     `REDIS_URL=redis://redis:6379/0`. Remove the `mongo` service and its volume.
   - **`.env.example`:** asyncpg URL, plus `REDIS_URL=redis://localhost:6380/0`.
     Mongo keys removed.
   - **CI:** replace the mongo service with redis, and set the env URLs to match.
6. `refactor(backend): async alembic env`
   - `migrations/env.py` moves to Alembic's async template
     (`async_engine_from_config` + `connection.run_sync(do_run_migrations)`).
   - The URL still comes from `get_settings()`.
7. `docs: update architecture for async db and redis`
   - Stack table, layout, backend architecture and ports.
   - Required by AGENTS.md in the same change.

**Verify:**

- `make check` passes.
- `make dev`, then `curl localhost:8000/healthz` returns `{"status":"ok"}`.
- `make db-migrate` runs on an empty database with no errors.

---

## Phase 1: identity and workspaces

Branch: `feat/workspaces`

**Shortcut, on purpose:** guest identity, with no passwords.

- A user types a display name and gets an opaque session token, stored in Redis
  (`session:<token>` → user id, 7-day TTL).
- Anyone with a workspace link can join.
- Upgrade path: real sign-in (KITH-style argon2 + JWT) if the product outlives
  the hackathon.

Commits:

1. `feat(backend): add user, workspace and member models`
   - Tables:
     - `user`: id, display_name, created_at
     - `workspace`: id, slug (unique), name, created_at
     - `workspace_member`: workspace_id, user_id, joined_at, primary key on both
   - Register the models in `app/models/__init__.py`, generate the revision,
     and review it.
2. `feat(backend): guest sessions`
   - `POST /session {display_name}` returns `{token, user}`.
   - A `current_user` dependency reads `Authorization: Bearer <token>` and
     looks it up in Redis.
3. `feat(backend): create, join and read workspaces`
   - `POST /workspaces`
   - `POST /workspaces/{slug}/join`
   - `GET /workspaces/{slug}` (members only)
   - Layering starts here: `routes/` → `services/` → `repositories/`, with
     request and response models in `schemas/`.
4. `test(backend): workspace membership rules`
   - A non-member gets 403.
   - Joining twice is a no-op.
   - An unknown slug gets 404.

---

## Phase 2: realtime transport (backend)

Branch: `feat/realtime`

**Design:**

- One WebSocket per tab: `/ws/{workspace_id}?ticket=...`.
- **Ticket:** `POST /realtime/ticket` stores `ws:ticket:<t>` → user id in Redis
  for 30 seconds. The WebSocket consumes it once with `GETDEL`, so the session
  token never appears in a URL.
- **Hub:** an in-process registry, one hub per workspace, holding that
  workspace's connections.
- **Fan-out:** one Redis pub/sub channel per workspace (`ws:events:<id>`),
  carrying every outbound message. KITH uses four separate buses; we merge them
  into one. Each hub publishes to the channel and listens on it, so it keeps
  working with several uvicorn workers.
- **Presence:** a Redis hash `presence:<workspace_id>` mapping user id to their
  last-seen time. A background task in `lifespan` removes stale entries and
  broadcasts a `presence.leave` for each.

Commits:

1. `feat(backend): websocket message types`
   - `app/ws/protocol.py`: Pydantic discriminated unions plus `TypeAdapter`s.
   - Client → server: `hello`, `cursor.move`.
   - Server → client: `presence.join`, `presence.leave`, `cursor.move`, `event`.
   - Close codes: 4401 for a bad ticket, 4403 for a non-member.
2. `feat(backend): realtime ticket route`
3. `feat(backend): workspace hub with redis pub/sub fan-out`
   - Cursor positions are batched on a 50 ms tick, keeping only the latest
     position per user.
4. `feat(backend): presence tracking and stale reaper`
5. `feat(backend): websocket route`
   - Steps: check the ticket, then check membership, then accept, register with
     the hub, and announce the presence join. Then the receive loop runs; a
     message that fails validation is dropped and the connection stays open.
     On disconnect, the user's presence entry is removed and the connection
     unregistered.
6. `feat(infra): proxy websockets in vite and nginx`
   - Vite: `ws: true` on the `/api` proxy.
   - Nginx: `proxy_http_version 1.1`, `Upgrade`/`Connection` headers, and
     `proxy_read_timeout 1h`.
7. `test(backend): websocket auth, presence and broadcast`
   - Uses `TestClient.websocket_connect`.
   - A bad ticket and a reused ticket both get 4401.
   - A non-member gets 4403.
   - When two clients connect, each sees the other's join and cursor.
   - A malformed message doesn't close the socket.

---

## Phase 3: frontend shell and presence

Branch: `feat/frontend-realtime`

Commits:

1. `feat(frontend): api client and guest session`
   - A fetch wrapper that adds the bearer token, with the token kept in
     localStorage.
   - A name-entry screen.
2. `feat(frontend): create and join workspace by link`
   - Routes: `/` and `/w/:slug`.
   - Add `react-router-dom` only if parsing `location.pathname` by hand gets
     messy.
3. `feat(frontend): realtime client with reconnect`
   - Gets a fresh ticket on every connect.
   - Reconnects with jittered exponential backoff (250 ms up to 8 s).
   - Tracks a status: connecting, live, reconnecting, error.
   - No web worker yet; add one only if cursor traffic causes jank.
4. `feat(frontend): online members and live cursors`
5. `test(frontend): realtime client reconnect and message handling`

**Verify:** two browsers on the same `/w/:slug` URL see each other's cursors.
Killing the backend shows "reconnecting", and restarting it recovers.

---

## Phase 4: drafts and team review

Branch: `feat/drafts`

**Design:**

- A draft is a document of fields: one draft is one grant application, one
  outreach message, or one post.
- Durable writes go through REST, are versioned, and are broadcast as `event`
  messages.
- Locks and live typing are short-lived and live only in Redis and the socket.

Commits:

1. `feat(backend): draft, draft field and approval models`
   - `draft`: id, workspace_id, kind (`grant` / `outreach` / `post`), title,
     status (`drafting`, `in_review`, `approved`), idempotency_key (unique),
     created_at.
   - `draft_field`: id, draft_id, label, value, limit_chars, status (`drafted`,
     `needs_input`, `cant_verify`), sources (JSONB list of
     `{url_or_field, retrieved_at, quote}`), version.
   - `approval`: draft_id, user_id, approved_at.
2. `feat(backend): read drafts, edit fields and approve`
   - `PATCH /drafts/{id}/fields/{fid}` takes `{value, version}` and returns 409
     if the version is stale.
   - `POST /drafts/{id}/approve`.
   - Every write publishes `draft.field.updated` or `draft.approved`.
3. `feat(backend): field edit locks and live typing`
   - Client messages: `field.lock`, `field.unlock`, `field.typing`.
   - A lock is `SET lock:<field> <user> NX EX 15`, refreshed while the user
     types and released when they disconnect.
   - Typing previews are batched per field on the tick and sent to everyone
     except the person typing.
   - A typing message from someone who doesn't hold the lock is dropped.
     KITH left this unchecked.
4. `feat(frontend): draft review view`
   - Fields show their status badges and sources.
   - Each field has a lock indicator and a copy button.
   - An approve button.
5. `test: lock contention, stale version, approve broadcast`

---

## Phase 5: run engine and Crustdata client

Branch: `feat/runs`

**Design:** runs are rows in Postgres. A worker runs as an asyncio task inside
`lifespan`. It claims the next queued run with `SELECT ... FOR UPDATE SKIP
LOCKED` and executes its steps one by one, saving its position after each
step. On startup it puts orphaned runs back in the queue, so a crashed run
resumes from where it stopped.

Commits:

1. `feat(backend): run, run step and ledger models`
   - `run`: id, workspace_id, flow, input, status, idempotency_key (unique),
     credit_ceiling, deadline.
   - `run_step`: run_id, name, status, output (JSONB), attempt.
   - `ledger`: run_id, provider (`crustdata` / `llm`), endpoint, credits_or_tokens,
     request_hash, created_at.
2. `feat(backend): crustdata client`
   - httpx, using the `x-api-version: 2025-11-01` header.
   - Retries 429s and 5xxs with backoff, following `x-ratelimit-reset`.
   - A 402 stops the run.
   - Records every call in the ledger.
   - Caches responses in Redis by request hash, so a re-run never pays twice.
   - New settings: `crustdata_api_key`, plus a placeholder in `.env.example`.
3. `feat(backend): run worker with resume and ceilings`
   - When a run goes over its credit or time limit, it holds and waits for a
     person instead of failing silently.
4. `feat(backend): stream run progress`
   - A `run.step` event goes out on the workspace channel.
   - `POST /runs` takes an idempotency key, so starting the same run twice
     returns the existing run.
5. `test(backend): resume after crash, idempotent start, ceiling hold`
   - Uses a fake Crustdata transport.

---

## Phase 6: flows

### 6a. Grants (demo flow)

Branch: `feat/grants-flow`

Steps:

1. **Find grants:** `web/search` with `site:` and `start_date`.
2. **Fetch and extract:** `web/fetch` each grant page, and have the LLM extract
   the structured grant form. A form behind a login, or a fetch that's blocked,
   goes to `needs_input` and asks the team to upload the form.
3. **Merge duplicates:** a grant found twice becomes one record, keyed by portal
   + grant name.
4. **Check eligibility rule by rule** against the internal context. Each rule is
   `met`, `not met`, or `missing`.
5. **Draft** one field per question, each with its sources and its status.

- **Internal context for the demo:** facts uploaded from a company profile file.
  Full RAG and A-Mem come in phase 7.
- **Test case:**
  - A snapshot of one real grant open now, plus a seed company.
  - The right answers, written by hand before the run.
  - Edge cases: a duplicate grant, a changed deadline, and one rule the system
    can't verify.

### 6b onwards: the other domains (stretch, in this order)

Each one reuses the run engine and the review view for drafts. Their steps are
in the PRD under "Domains".

1. **Shared outreach step + investors (Fundraising):** builds the shared
   outreach step that 2 and 5 reuse.
2. **Change feed (6):** the hourly job plus the weekly digest. It also answers
   the handbook's "what changed at each account" sample request.
3. **Market research (1):** competitor brief and moat map.
4. **Market validation (2), Networking (5):** mostly reuse 1 and 3 above.
5. **GTM (3):** the plan document plus the content calendar.

---

## Phase 7: context layer (stretch)

- Switch the Postgres image to `pgvector/pgvector:pg17`. It's the same major
  version, so the existing volume keeps working.
- File upload, then chunking and embeddings, then retrieval.
- A-Mem tables:
  - `note`: content, keywords, tags, embedding, source, retrieved_at, derived
    flag.
  - `note_link`: links between notes.
- Source notes are never rewritten. Only derived notes evolve.
- An hourly refresh job, built on the run engine with a schedule row. Watchers
  later; see `docs/todos.md`.

---

## Phase 8: submission (start by 5:00 PM)

- README: the service, who pays today, the business case (₹ price and the cost
  of one run from the ledger), approaches considered, the hardest case, what we
  left out, and how to run it.
- Architecture diagram.
- Test cases with expected answers.
- A two-minute demo video.
- Repo set to public.
