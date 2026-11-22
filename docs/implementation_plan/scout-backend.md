# Implementation plan: Scout backend (FastAPI + Crustdata)

Written 22 Nov 2026, 13:30 IST, before work began. This is a historical plan; trust
the code once work lands.

**Spec:**
- [`scout-core.md`](../prd/scout-core.md)
- [`scout-onboarding-thesis.md`](../prd/scout-onboarding-thesis.md)
- [`scout-scoring-actions.md`](../prd/scout-scoring-actions.md)
- [`scout-dd-loop.md`](../prd/scout-dd-loop.md)

**Scope:** the FastAPI backend with Crustdata, plus an API contract (OpenAPI +
`docs/api/README.md`) that the frontend team builds against. We don't build the
frontend.

**Code freeze:** 18:00. Submission work starts at 17:15 at the latest.

## Ground rules that make parallel work possible

1. **Contract first.** Phase 0 defines every Pydantic request and response model and
   every route (initially returning `501`), and exports `docs/api/openapi.json`.
   The frontend team starts from it at about 14:15, and later phases fill in the
   route bodies without changing the contract. Any contract change needs a commit
   that re-exports the spec, and the frontend team is told.
2. **One migration, created in phase 0, for every table.** No agent writes a
   migration. If a column turns out to be missing, the integrator (the main
   session) adds it in a follow-up migration.
3. **The integrator alone owns the shared files:**
   - `app/main.py`
   - `app/models/*`
   - `migrations/`
   - `app/core/config.py`
   - `backend/.env.example`
   - `tests/conftest.py`
   - `pyproject.toml` / `uv.lock`
   
   An agent that needs a change in one of these says so in its report. Each agent's
   prompt lists exactly which files it owns.
4. **Everything is in place before an agent starts.** Phase 0 adds every
   dependency, setting, router include and job type. Agents only fill in modules
   they own.
5. **One worktree and branch per agent,** taken from the current phase branch. The
   integrator reviews each agent's report and code, re-runs `make check`, merges,
   then runs the phase demo.
6. **Tests never spend credits.**
   - The Crustdata, web and LLM clients take an injectable transport.
   - Tests replay recorded responses from `backend/tests/fixtures/`.
   - Each agent runs tests with its own `TEST_DB_SUFFIX` (Postgres) and
     `TEST_MONGO_DB`.
7. **Real calls happen only in the phase demos,** run by the integrator, and need
   `CRUSTDATA_API_KEY` and `OPENROUTER_API_KEY` in `backend/.env`. **Neither is set
   yet.**
8. **Conventions:**
   - AGENTS.md rules apply.
   - Commits are Conventional Commits with **no AI attribution** (CLAUDE.local.md).
   - Run checks with `set -o pipefail` so a piped command can't hide a failure.
   - Never apply migrations to the dev DB.

## Stack decisions

| Decision | Choice | Why |
|---|---|---|
| Database access | Keep the scaffold's **sync** SQLAlchemy + psycopg; routes are `def` | No time to migrate. The heavy work runs in a worker, not in requests. |
| Raw responses | Mongo collection `raw`, one document per `source`, never modified | The scaffold already has Mongo; facts point to their raw record |
| Background work | `job` table, plus a worker process (`python -m app.worker`) that claims jobs with `FOR UPDATE SKIP LOCKED`. Steps are saved in `run_step`. | Resumes after a crash; no Redis or Celery needed |
| Progress | SSE at `GET /runs/{id}/events`, polling `run_step` every second | Simple, works through the nginx and Vite proxies |
| HTTP | `httpx` for Crustdata, web, Gmail | One client library |
| LLM | **OpenRouter** (OpenAI-compatible chat API over `httpx`), Claude Sonnet 5.5 via BYOK; slugs in `LLM_MODEL` / `LLM_FAST_MODEL`. Structured output via one validated `submit` tool call. *(Changed from the Anthropic SDK during phase 0.)* | The team's Anthropic key is billed through OpenRouter |
| PDF parsing | `pypdf` (text per page) | Small, pure Python |
| Token encryption | `cryptography` (Fernet) | Gmail refresh tokens |
| Auth | **Shortcut:** no login. Requests carry an `X-Investor-Id` header after onboarding. | A single-tenant demo. Upgrade to real sessions after the hackathon. |

## Package layout (created as empty modules in phase 0)

```
backend/app/
  main.py · worker.py · core/config.py · deps.py
  models/            all tables (phase 0)
  schemas/           API contract (phase 0): common, investor, fund, thesis, profile,
                     search, candidate, outreach, memo, dd, source, run, watch, gmail
  routes/            one module per area, stubs in phase 0
  repositories/      DB access per area
  integrations/      crustdata.py · web.py · llm.py · gmail.py · recorder.py
  services/
    evidence/        facts_mapper.py · sources.py
    onboarding/      identity.py · name_matching.py · deals.py · thesis.py · profile.py
    search/          query_parser.py · discovery.py · grants.py
    scoring/         rules.py · engine.py · signals.py · actions.py
    actions/         outreach.py · questions.py · memo.py · status.py
    watch/           watcher.py · diff.py
    dd/              gaps.py · ingest.py · claims.py · verify.py
    jobs/            runner.py · handlers registry
  profile_rules.json
backend/tests/fixtures/{crustdata,web,llm,docs}/
docs/api/openapi.json · docs/api/README.md
```

---

## Phase 0: foundation and API contract (13:35 → 14:20)

Branch: `feat/scout-foundation`. Three tracks run in parallel.

| Track | Owner | Files | Delivers |
|---|---|---|---|
| **0A: models and infrastructure** | Integrator (main session) | `models/*`, `migrations/`, `core/config.py`, `.env.example`, `tests/conftest.py`, `pyproject.toml`, `worker.py`, `services/jobs/*`, `main.py` | Every table from the PRDs in one reviewed migration. Settings: `CRUSTDATA_API_KEY`, `ANTHROPIC_API_KEY`, the Google keys, `TOKEN_ENCRYPTION_KEY`, `WEBHOOK_SECRET`, `DD_*`, `RUN_CREDIT_CEILING`. Isolated test databases (Postgres `<db>_<suffix>`, Mongo `<db>_<suffix>`). The job table, the worker loop, a handler registry, the run/step checkpoint helpers, and `GET /runs/{id}` + SSE. All dependencies added. |
| **0B: API contract** | Agent `contract` (worktree) | `schemas/*`, `routes/*` (stubs), `scripts/export_openapi.py`, `docs/api/*`, a Makefile `openapi` target | Every route in the PRDs with full request and response models, enums for every status, an example on every model, and the error format `{error: {code, message, details}}`. Stubs return `501`. `make openapi` writes `docs/api/openapi.json`. `docs/api/README.md` covers the flows (which calls, in which order), the auth header, the SSE event format, status diagrams and polling guidance. |
| **0C: integrations** | Agent `integrations` (worktree) | `integrations/crustdata.py`, `web.py`, `llm.py`, `recorder.py`, `tests/fixtures/*`, tests | **Clients:** the Crustdata client with both headers. It retries 429s using `x-ratelimit-reset` with jittered backoff, retries 5xx, stops on 402, and treats a timeout as `SourceUnavailable`, never as an empty result. It caches by request hash. Every call goes through a `Recorder` interface that will write `source`, `raw` and `ledger` (an in-memory fake for now). The web client (`/web/search/live`, `/web/enrich/live`) works the same way. **LLM wrapper:** calls a tool with a JSON schema and returns validated Pydantic objects. It has a `quote_check(text, quote)` helper and a fake LLM for tests. **Fixtures:** representative JSON for each endpoint we use, built from the docs' examples and labelled as such. |

**Merge order:** 0A first (it owns `main.py` and the dependencies), then 0B, then 0C.
The integrator wires each router into `main.py`.

**Testable result:**
- `make check` passes.
- `make openapi` produces the spec; `/docs` lists every endpoint.
- The client tests pass: retry on 429, stop on 402, cache hit, timeout raises.
- A worker job runs, crashes at step 2, restarts, and resumes from step 2 (test).
- **Handoff:** `docs/api/openapi.json` + `docs/api/README.md` go to the frontend team.

## Phase 1: evidence and onboarding (14:20 → 15:15)

Branch: `feat/scout-onboarding`. Three agents, plus the integrator wiring the `Recorder` to the DB.

| Track | Agent | Owns | Delivers |
|---|---|---|---|
| **1A: evidence** | `evidence` | `services/evidence/*`, `repositories/sources.py`, `repositories/facts.py`, `routes/sources.py` | `facts_mapper`: fixed mappings from Crustdata person and company JSON paths to `fact` rows, each with `as_of`, the field path as `locator`, and `extracted_by=rule`. Covers funding milestones, headcount over time, founders, education, experience, taxonomy and news. Includes the DB-backed `Recorder` and `GET /sources/{id}` (raw snapshot + locator). |
| **1B: identity and firm** | `identity` | `services/onboarding/identity.py`, `name_matching.py`, `routes/investors.py`, `routes/funds.py` | `POST /investors/onboard` (LinkedIn, or name + firm → people to confirm), `confirm-identity`, `GET /funds/{id}/alias-candidates` (name variants → search → `investors_detailed` grouped by permalink → 3 example companies each), `POST /funds/{id}/aliases`. Name matching is a pure module tested with the Accel / Accel-KKR / Accel India / Peak XV cases. |
| **1C: deals, thesis, profile** | `thesis` | `services/onboarding/deals.py`, `thesis.py`, `profile.py`, `profile_rules.json`, `routes/theses.py`, `routes/scoring_profiles.py` | Strict round matching into `deal` rows (exact canonical name; "date unknown" when no round names the firm). Thesis points and confidence as pure functions over deals. Profile derivation rules (pure, driven by the JSON file), with every change stored with its reason and evidence. GET/PUT/confirm routes. |

**Integrator:** registers an `onboarding` job handler that chains identity → aliases
(waits for confirmation) → portfolio search → deals → thesis → profile, with a
checkpoint after each step.

**Testable result:**
- Unit tests for name matching, deal matching, thesis and profile derivation, using
  the fixed cases from the PRD.
- An API-level test of the full onboarding flow on the fake transport.
- **Live demo (needs keys):** onboard one real partner at a known Indian fund. Check
  that the deals, thesis and profile come out with sources. **This also settles the
  "Indian seed coverage" open question.** If coverage is poor, adjust the window and
  the fallback before phase 2.

## Phase 2: search, discovery and scoring (15:15 → 16:10)

Branch: `feat/scout-search`.

| Track | Agent | Owns | Delivers |
|---|---|---|---|
| **2A: query parsing** | `query` | `services/search/query_parser.py`, `routes/searches.py` (create, filters) | LLM → filter spec, using the contract's JSON schema. Each value is checked against the matching autocomplete endpoint (free). Values that can't be resolved are returned as `unresolved` with suggestions. Covers `POST /searches` and `PUT /searches/{id}/filters`. |
| **2B: discovery** | `discovery` | `services/search/discovery.py`, `grants.py`, `repositories/candidates.py` | People route (founder titles + education → current companies) and company route (semantic company search → `people.founders`), merged and de-duplicated by Crustdata id. Enrichment into facts goes through 1A. Grant checks: `web/search` with `site:` and `start_date`, then fetch, then an LLM quote extraction kept only if `quote_check` passes, else `unverifiable`. A credit limit applies. |
| **2C: scoring** | `scoring` | `services/scoring/*`, `repositories/scores.py` | The criteria library rules, the engine (unknown handling, completeness, evidence weighting and source tiers), signals, the suggested-action table and `score_snapshot`. All pure and table-tested. |

**Integrator:** registers a `search_run` job: discovery → enrichment → grants →
scoring, then fills `GET /searches/{id}` and `GET /candidates/{id}`.

**Testable result:**
- Scoring and action unit tests.
- A full search on the fake transport returns ranked candidates, each with a
  breakdown, completeness, signals and a suggested action, and every fact linked to
  a source.
- **Live demo:** the handbook-style query ("BITSian deeptech startups…") returns a
  real ranked list. Any grants show `verified` with a quote, or `unverifiable`.

## Phase 3: actions, memo and watch (16:10 → 16:50), in parallel with phase 4

Branch: `feat/scout-actions`.

| Track | Agent | Owns | Delivers |
|---|---|---|---|
| **3A: status and outreach** | `outreach` | `services/actions/status.py`, `outreach.py`, `questions.py`, `routes/candidates.py` (status, rescore), `routes/outreach.py` | A status state machine with only the allowed transitions (overrides record who and why). Questions tied to the gap, fact or claim behind them. Outreach drafts, then `approve`, then `send` (copy-paste mode: `mark-sent`). Uses the idempotency key. |
| **3B: memo** | `memo` | `services/actions/memo.py`, `routes/memos.py` | Fixed sections written only from cited facts and claims. A post-check removes any sentence with a number or date not found in its cited items, and lists the removals. Versioned, with a `stale` flag. |
| **3C: watch** | `watch` | `services/watch/*`, `routes/watch.py`, `routes/webhooks.py` | Creating a `/watch/company`, `POST /webhooks/crustdata/watch` (checks `WEBHOOK_SECRET`), the test notification, `POST /candidates/{id}/recheck` (re-enrich → compare facts → `watch_event` with a suggested action), and `GET /watch-events`. |

**Testable result:** an API test that goes shortlist → outreach approved → marked
sent; then invest → memo with citations, plus the post-check removing a planted
unsupported number; then watch → test webhook → `watch_event`.

## Phase 4: the DD loop (16:10 → 17:15), in parallel with phase 3

Branch: `feat/scout-dd`.

| Track | Agent | Owns | Delivers |
|---|---|---|---|
| **4A: ingestion** | `ingest` | `services/dd/ingest.py`, `claims.py`, `routes/documents.py` | `POST /candidates/{id}/documents` (allowed types, size cap, de-duplicated by sha256), PDF text per page into Mongo, and claim extraction kept only when the quote is found on the page. |
| **4B: verification and DD flow** | `verify` | `services/dd/gaps.py`, `verify.py`, `routes/dd.py` | Gap analysis → `dd_item`s + the request draft. Verifiers for headcount, funding and founder background (±15% tolerance, 60-day date window) → `verification` → rescore → snapshot showing what changed. Moves the candidate through the `dd_stage` stages. |
| **4C: Gmail (stretch)** | `gmail` | `integrations/gmail.py`, `routes/integrations.py`, the `poll_gmail` handler | OAuth connect and callback with an encrypted token. Exactly-once sending (the `X-Scout-Outreach-Id` header + Sent-folder check). Polling history only for known threads. Attachments go into 4A. **Only if the Google Cloud setup is done by 15:30.** |

**Testable result:**
- Upload the team-made test deck, which states 40 engineers while the fixture says 18.
- Expected: claims extracted with quotes, headcount `contradicted` with both sources,
  a red flag plus a follow-up question, and a lower score in the score history.
- With Gmail: a teammate's reply with an attachment updates the checklist on its own.

## Phase 5: hardening and submission (17:15 → 18:00)

The integrator does this alone.

- Robustness tests:
  - kill the worker mid-search and restart, with no duplicate candidates
  - re-upload a deck, with no duplicate claims
  - a send crash resolved by the reconciliation check
  - a 429 storm absorbed by the retries
- A demo seed script: onboard a partner → search → shortlist → DD with the test
  deck → memo.
- README:
  - the service and who pays for it today
  - the business case, priced in ₹ with the cost per run from the ledger
  - the approaches considered, the hardest case, and what was cut
  - how to run it
  - the diagram
- Regenerate `docs/api/openapi.json`; update `docs/architecture.md`.
- Record the 2-minute demo video. Make the repo public.

## Cut order if late

1. 4C Gmail → upload only
2. 3C watch → test notification only
3. 2B grants → shown as `unverifiable` with a note
4. Calibration against peers (already a stretch goal)

Never cut source tracking, the quote check, approval before sending, or the ledger.

## Checklist for each merge

1. Review the agent's report and diff against its brief, including the files it owns.
2. `make check` with `set -o pipefail`. Backend tests run against the isolated DBs.
3. Merge into the phase branch.
4. Run the phase's testable result (live demo where keys exist).
5. Re-export the OpenAPI spec if any schema changed.
6. At the end of each phase: open a PR to `main` with the template filled in, and
   merge once CI is green.

## Prerequisites (the user)

- [ ] `CRUSTDATA_API_KEY` in `backend/.env` (redeem promo `CONTEXTCONBITS`)
- [ ] `OPENROUTER_API_KEY` in `backend/.env` (Anthropic key attached in OpenRouter as BYOK)
- [ ] Google Cloud OAuth client + test users, if Gmail is wanted (needed by 15:30)
- [ ] A real partner name and firm for the phase 1 live demo
