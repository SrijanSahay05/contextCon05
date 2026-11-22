# Phase 0 in detail: foundation and API contract

Part of [`scout-backend.md`](scout-backend.md). Written 22 Nov 2026 before work began.

**Branch:** `feat/scout-foundation`, taken from `docs/scout-prds` (so the PRDs and plan come along).
**Time box:** 13:35 → 14:20.

There are three tracks. 0A is done by the integrator; 0B and 0C are each done by an
agent in its own worktree.

---

## 0A: models and infrastructure (integrator)

### Dependencies (`uv add`)

- **Runtime:** `httpx`, `anthropic`, `pypdf`, `cryptography`.
- **Tests:** `httpx.MockTransport` is built in, so no `respx`. SSE uses FastAPI's
  `StreamingResponse`, so no `sse-starlette`.

### Settings (`app/core/config.py` + `.env.example` placeholders)

| Key | Default | Use |
|---|---|---|
| `CRUSTDATA_API_KEY` | — (required only for live calls) | Crustdata |
| `CRUSTDATA_BASE_URL` | `https://api.crustdata.com` | Tests point it elsewhere |
| `ANTHROPIC_API_KEY` | — | LLM |
| `LLM_MODEL` / `LLM_FAST_MODEL` | `claude-sonnet-5-5` / `claude-haiku-5-5` | |
| `RUN_CREDIT_CEILING` | `300` | Default credit limit per run |
| `RUN_DEADLINE_MINUTES` | `20` | Default time limit per run |
| `CACHE_MAX_AGE_HOURS` | `24` | Reuse an identical Crustdata request within this window |
| `WEBHOOK_SECRET` | — | Crustdata watch webhook |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | — | Gmail (stretch) |
| `TOKEN_ENCRYPTION_KEY` | — | Fernet key for Gmail tokens |
| `DD_REMINDER_DAYS` / `DD_TIMEOUT_DAYS` | `5` / `14` | DD timers |
| `UPLOAD_DIR` / `UPLOAD_MAX_MB` | `./uploads` / `25` | Documents |

### Model conventions

- Entity ids are `uuid`. High-volume tables (`fact`, `ledger`, `job`) use
  `bigint identity`.
- Timestamps are `timestamptz`. The `Base` sets a type map so every `datetime`
  column gets this.
- Enums are `sqlalchemy.Enum(..., native_enum=False)`: stored as text with a check
  constraint, so they're cheap to change. The Python `StrEnum`s live in
  `app/models/enums.py`, and **the API schemas import the same enums**, so the
  contract and the database can't drift apart.
- JSON is stored as `JSONB`. Arrays of ids are stored as JSONB lists, which is
  simpler than Postgres arrays given the mixed id types.

### Tables (all in one migration, `0001_scout_schema`)

| Table | Columns (constraints) |
|---|---|
| `investor` | id, name, linkedin_url (unique, nullable), crustdata_person_id (bigint), fund_id → fund, title, identity_confirmed_at, created_at |
| `fund` | id, name, crustdata_company_id (bigint unique), domain, created_at |
| `fund_alias` | id, fund_id → fund, permalink, canonical_name, confirmed_by → investor, confirmed_at, source_id → source; **unique (fund_id, permalink)** |
| `company` | id, crustdata_company_id (**unique**), name, domain, created_at |
| `person` | id, crustdata_person_id (**unique**), name, linkedin_url |
| `company_person` | company_id, person_id, role; **pk (company_id, person_id, role)** |
| `source` | id, kind (`crustdata`/`web`/`news`/`email`/`upload`/`llm`), endpoint_or_url, request_hash (index), retrieved_at, raw_id (Mongo id), reliability_tier (`A`/`B`/`C`), run_id → run (nullable) |
| `fact` | id (bigint), subject_type (`company`/`person`/`fund`/`investor`), subject_id, predicate, value (jsonb), as_of (date, nullable), observed_at, source_id → source, locator (jsonb: `{path}` or `{page, quote}`), extracted_by (`rule`/`llm`); index (subject_type, subject_id, predicate) |
| `deal` | id, fund_id, company_id, round_date (nullable), round_type, amount_usd (numeric), led (nullable), match_rule, match_evidence (jsonb), championed_by_investor_id (nullable), source_id; **unique (fund_id, company_id, round_date, round_type)** |
| `investor_post_link` | investor_id, company_id, source_id; pk on all three |
| `thesis` | id, investor_id, fund_id, version, status (`draft`/`confirmed`), window_start, window_end, deal_count, confidence (`high`/`medium`/`low`), points (jsonb), summary, created_at; **unique (investor_id, version)** |
| `scoring_profile` | id, investor_id, thesis_id, version, status (`draft`/`confirmed`), origin (`derived`/`edited`/`generic`), confidence, criteria, thresholds, self_reported_weight, source_tiers, derivation (jsonb), created_at; **unique (investor_id, version)** |
| `search` | id, investor_id, query_text, parsed_filters, unresolved (jsonb), as_of (nullable), thesis_id, profile_id, status (`draft`/`confirmed`/`running`/`done`/`failed`), run_id, created_at |
| `run` | id, kind (`onboarding`/`search`/`dd`/`recheck`/`memo`), status (`queued`/`running`/`done`/`failed`/`held`), subject (jsonb), credit_ceiling, credits_spent, deadline, started_at, finished_at, error, hold_reason |
| `run_step` | run_id, name, seq, status, output (jsonb), attempt, started_at, finished_at; **pk (run_id, name)** |
| `job` | id (bigint), run_id, kind, payload, status (`queued`/`running`/`done`/`failed`/`held`), idempotency_key (**unique**), attempts, max_attempts (3), run_after, locked_at, locked_by, last_error, created_at |
| `ledger` | id (bigint), run_id (nullable), provider (`crustdata`/`web`/`llm`/`gmail`), endpoint, units (numeric), unit_type (`credits`/`input_tokens`/`output_tokens`), request_hash, source_id, cached (bool), created_at |
| `candidate` | id, search_id, company_id, status (`new`/`shortlist`/`in_dd`/`invest`/`watch`/`pass`), dd_stage (nullable), score, completeness, breakdown, profile_version, suggested_action (`reach_out`/`request_data`/`watch`/`pass`/`invest`), suggested_reason, override (jsonb), updated_at; **unique (search_id, company_id)** |
| `signal` | id, candidate_id, kind (`strong`/`red_flag`/`gap`), text, fact_ids, claim_ids, created_at |
| `question` | id, candidate_id, text, motivated_by (`{type, id}`), status (`draft`/`approved`/`sent`/`answered`), answer_claim_id |
| `outreach` | id, candidate_id, dd_request_id, channel (`email`/`linkedin`), to_address, subject, body, status (`draft`/`approved`/`sending`/`sent`/`replied`), idempotency_key (**unique**), approved_by, approved_at, sent_at, gmail_message_id, gmail_thread_id |
| `memo` | id, candidate_id, version, markdown, citations, removed, stale, generated_at; **unique (candidate_id, version)** |
| `score_snapshot` | id, candidate_id, score, completeness, breakdown, profile_version, trigger (`initial`/`dd_ingest`/`watch_event`/`profile_change`/`override`), delta, created_at |
| `watch` | id, company_id, candidate_id, crustdata_watch_id, reason (`watch`/`pass`), status, created_at |
| `watch_event` | id, watch_id, source_id, changes, suggested_action, status (`open`/`acted`/`dismissed`), created_at |
| `dd_request` | id, candidate_id, round, outreach_id, status, upload_token_hash, expires_at, created_at |
| `dd_item` | id, dd_request_id, kind (`deck`/`data_room`/`financials`/`cap_table`/`grant_letter`/`customer_refs`/`answer`), status (`requested`/`received`/`received_needs_access`/`verified`/`contradicted`/`unverifiable`), document_id, satisfied_by_message_id |
| `document` | id, candidate_id, kind, origin (`email`/`vc_upload`/`founder_upload`/`public`), storage_path, mime, sha256, parse_status, page_count, source_id; **unique (candidate_id, sha256)** |
| `claim` | id, candidate_id, document_id, message_id, page, quote, predicate, value, as_of, created_at |
| `verification` | id, claim_id, result (`verified`/`contradicted`/`unverifiable`/`self_reported`), fact_ids, note, tolerance_used, created_at |
| `mail_account` | id, investor_id (**unique**), email, refresh_token_enc, history_id, scopes, status |
| `mail_thread` | id, dd_request_id, gmail_thread_id (**unique**) |
| `mail_message` | id, mail_thread_id, gmail_message_id (**unique**), direction, received_at, processed_at, raw_id |

**Mongo collections:**
- `raw`: one document per `source`, never modified.
- `document_pages`: `{document_id, page, text}`.
- `mail_bodies`.

### Worker and jobs

- **`services/jobs/queue.py`**
  - `enqueue(kind, payload, idempotency_key, run_id)`: inserts with
    `ON CONFLICT (idempotency_key) DO NOTHING` and returns the existing job if
    there is one.
  - `claim(worker_id)`: one `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED
    LIMIT 1) RETURNING *`.
- **`services/jobs/steps.py`**: `StepRunner(run_id).step(name, fn)`.
  - If the step is already `done`, it returns the saved `output`.
  - Otherwise it runs `fn`, saves the output and marks the step done.
  - Handlers are written only as sequences of `step(...)` calls. That's what makes
    them resumable.
- **`services/jobs/registry.py`**: maps each job `kind` to its handler. Phase 0
  registers only a test handler, `noop_two_step`.
- **Limits:** before each external call, `ensure_budget(run_id)` sums the ledger. It
  raises `CeilingReached` when over the credit limit and `DeadlinePassed` after the
  deadline. Either one sets the run to `held` with a `hold_reason`.
- **Failures:**
  - A failed job gets `attempts + 1` and `run_after = now + 2^attempts × 5 s`.
  - At `max_attempts` it becomes `held`, meaning it needs a person. It is never
    silently dropped.
- **On startup:** `running` jobs whose `locked_at` is more than 10 minutes old go
  back to `queued`. This is the crash recovery.
- **Running it:**
  - `app/worker.py` loops: claim → dispatch → sleep 0.5 s when idle.
  - `make worker` runs it, and a `worker` service is added to compose using the same
    image and env as the backend.

### Runs API (implemented by 0A; the schemas come from 0B)

- **`GET /runs/{id}`** returns the status, steps, credits spent, hold reason, and the
  last 50 ledger rows.
- **`GET /runs/{id}/events`** is an SSE stream that checks the database every second
  and emits changes:

  | Event | Data | When |
  |---|---|---|
  | `step` | `{name, status, seq}` | A step changes |
  | `run` | `{status, credits_spent}` | The run changes |
  | `end` | — | The run is `done`, `failed` or `held` |

### Test setup (`tests/conftest.py`)

- `TEST_DB_SUFFIX` (default `test`) and `TEST_MONGO_DB` (default `<db>_test`) are set
  as env vars before any app import.
- **Per session:**
  - create the Postgres test database
  - `alembic upgrade head` against **it only**
  - drop the Mongo test database
- **Per test:** truncate every table (the list comes from `Base.metadata`) and clear
  the Mongo collections.
- **Fixtures:** `client` (TestClient with lifespan), `db` (a session),
  `fake_transport` (a `MockTransport` serving the fixture files).

**Make targets:** `worker`, `openapi`.

---

## 0B: API contract (agent `contract`)

**Owns:**
- `app/schemas/*` (except `enums` re-exports)
- `app/routes/*.py` (new modules only)
- `scripts/export_openapi.py`
- `docs/api/*`
- the `tests/test_contract.py` file

**Reads:** `app/models/enums.py`, which the integrator commits first, before the agent
starts.

### Conventions

- **Field names:** JSON is snake_case.
- **Ids:** uuid, except `fact` and `ledger`, which are integers.
- **Timestamps:** ISO-8601 in UTC.
- **Auth header (shortcut):** `X-Investor-Id: <uuid>` is required on everything except
  `POST /investors/onboard`, `GET /healthz`, the webhooks and the OAuth callback.
  It's provided through a dependency `current_investor_id`.
- **Errors:** always `{"error": {"code": "not_found", "message": "...", "details": {}}}`.
  The codes are `not_found`, `validation_error`, `conflict`, `not_allowed`,
  `upstream_unavailable`, `credits_exhausted`, `ceiling_reached` and
  `not_implemented`.
- **Long-running operations** return `202 {"run_id": "...", "status_url": "/runs/{id}", "events_url": "/runs/{id}/events"}`.
- **Lists** use `?limit=` (default 50) and `?offset=`, and return `{items, total}`.

### Shared evidence models (`schemas/common.py`)

```python
class Citation(BaseModel):    # how every fact/claim points to its origin
    source_id: UUID; kind: SourceKind; endpoint_or_url: str
    retrieved_at: datetime; locator: dict; quote: str | None = None
    reliability_tier: Literal["A", "B", "C"]

class FactOut(BaseModel):
    id: int; predicate: str; value: Any; as_of: date | None; citation: Citation

class ClaimOut(BaseModel):
    id: UUID; predicate: str; value: Any; as_of: date | None
    page: int | None; quote: str; verification: VerificationOut | None
```

### Routes and models

Every model carries an example (`json_schema_extra`).

| Group | Route | Request → Response |
|---|---|---|
| Investors | `POST /investors/onboard` | `OnboardRequest {linkedin_url} \| {name, firm}` → `IdentityCandidates {investor_id, candidates: [PersonCandidate]}` |
| | `POST /investors/{id}/confirm-identity` | `ConfirmIdentity {crustdata_person_id}` → `RunAccepted` |
| | `GET /investors/{id}` | → `InvestorOut` (profile, fund, onboarding state, current thesis/profile ids) |
| Funds | `GET /funds/{id}/alias-candidates` | → `[AliasCandidate {permalink, canonical_name, example_companies, preselected}]` |
| | `POST /funds/{id}/aliases` | `ConfirmAliases {permalinks}` → `RunAccepted` (continues onboarding) |
| Theses | `GET /theses/{id}`, `PUT /theses/{id}`, `POST /theses/{id}/confirm` | `ThesisEdit` → `ThesisOut {points: [ThesisPoint {dimension, statement, value, deal_ids}], confidence, window, deals: [DealOut]}` |
| Profiles | `GET/PUT /scoring-profiles/{id}`, `POST /scoring-profiles/{id}/confirm` | `ProfileEdit` → `ScoringProfileOut {criteria: [Criterion {key, weight, rule, params}], thresholds, derivation: [DerivationStep {target, change, reason, evidence_ids}], origin, confidence}` |
| Searches | `POST /searches` | `SearchCreate {query, as_of?}` → `SearchOut {parsed_filters: FilterSpec, unresolved: [Unresolved {term, suggestions}]}` |
| | `PUT /searches/{id}/filters` | `FilterSpec` → `SearchOut` |
| | `POST /searches/{id}/run` | → `RunAccepted` |
| | `GET /searches/{id}`, `GET /searches` | → `SearchOut` with `candidates: [CandidateSummary]`, sorted by score |
| Candidates | `GET /candidates/{id}` | → `CandidateOut` (company, founders, breakdown `[CriterionScore {key, score \| "unknown", weight, reason, facts: [FactOut], claims: [ClaimOut]}]`, completeness, signals, questions, suggested action, score history) |
| | `POST /candidates/{id}/status` | `StatusChange {status, reason?}` → `CandidateOut` (`409 not_allowed` for a transition that isn't allowed) |
| | `POST /candidates/{id}/rescore`, `POST /candidates/{id}/recheck` | → `CandidateOut` / `RunAccepted` |
| Outreach | `POST /candidates/{id}/outreach` | `OutreachCreate {channel, purpose}` → `OutreachOut` |
| | `PUT /outreach/{id}`, `POST /outreach/{id}/approve`, `/send`, `/mark-sent` | `OutreachEdit` → `OutreachOut` |
| Memos | `POST /candidates/{id}/memo`, `GET /memos/{id}` | → `RunAccepted` / `MemoOut {markdown, citations, removed, stale}` |
| DD | `POST /candidates/{id}/dd`, `GET /candidates/{id}/dd` | → `DDOut {stage, items: [DDItemOut], claims, verifications, thread, score_history}` |
| | `POST /dd/{id}/approve`, `/send`, `/mark-sent` | → `DDOut` |
| Documents | `POST /candidates/{id}/documents` (multipart) | → `DocumentOut {id, kind, parse_status, run_id}` |
| Sources | `GET /sources/{id}` | → `SourceOut {citation, raw}` |
| Runs | `GET /runs/{id}`, `GET /runs/{id}/events` | → `RunOut {status, steps, credits_spent, hold_reason, ledger}` / SSE |
| Watch | `GET /watch-events`, `POST /watch-events/{id}/dismiss` | → `{items: [WatchEventOut], total}` |
| Webhooks | `POST /webhooks/crustdata/watch` | Crustdata payload → `204` |
| Gmail | `GET /integrations/gmail/connect`, `GET /integrations/gmail/callback`, `DELETE /integrations/gmail`, `GET /integrations/gmail` | → redirect / `GmailStatus` |

Phase 0 keeps `GET /healthz` and the runs routes real; everything else returns `501`
with the error format.

### `FilterSpec`

A typed form of what Crustdata accepts, so the frontend can render it as chips:
`{people: [Condition], companies: [Condition], funding: [Condition], grants:
GrantFilter?, window_months?}`. `Condition` is `{field, op, value, display}`, with
`op` one of `=`, `in`, `>`, `<`, `contains`, `semantic`.

### `docs/api/README.md`

- Base URL `/api` and the auth header
- The error format and the list of codes
- The long-run pattern: `202` → SSE (with event names) → poll the run
- Each flow as an ordered list of calls, with the screen that uses it:
  onboarding (identity → aliases → thesis → profile), search, candidate review,
  outreach, DD, watch
- Status diagrams: candidate statuses, `dd_stage`, outreach
- How to regenerate the spec: `make openapi`

### Tests

- `test_contract.py`:
  - every route is in the OpenAPI spec
  - every model has an example
  - a stub returns `501` in the error format
  - `/healthz` works
  - `X-Investor-Id` is required where it should be

---

## 0C: integrations (agent `integrations`)

**Owns:** `app/integrations/*`, `tests/fixtures/{crustdata,web,llm}/*`, and
`tests/test_integrations_*.py`.

### Recorder interface (`integrations/recorder.py`)

The integrator writes the database-backed version in phase 1. 0C ships the protocol
plus an in-memory fake.

```python
class Recorder(Protocol):
    def lookup(self, request_hash: str, max_age: timedelta) -> CachedResponse | None: ...
    def record(self, *, provider: str, endpoint: str, request: dict, response: Any,
               units: float, unit_type: str, cached: bool, run_id: UUID | None,
               kind: str, url: str | None = None) -> UUID:  # returns source_id
        ...
```

### `CrustdataClient(settings, recorder, transport=None, run_id=None)`

**Methods**, each returning `CrustResult {data, source_id, credits, cached}`:
- `company_search`, `company_enrich`, `company_identify`, `company_autocomplete`
- `person_search`, `person_enrich`, `person_autocomplete`
- `job_search`, `social_post_search`
- `watch_company_create`, `watch_test_notification`, `watch_runs`
- `credits_balance` (free)

**Request handling:**
- Headers: `authorization: Bearer …`, `x-api-version: 2025-11-01`, `content-type`.
- `request_hash` = sha256 of the endpoint + the JSON body with sorted keys.

**Retries and errors:**

| Response | Behaviour |
|---|---|
| Cache hit within `CACHE_MAX_AGE_HOURS` | Return without calling; record `cached=true` with 0 credits |
| 429 | Wait `x-ratelimit-reset` (capped at 30 s, with jitter); up to 5 tries |
| 5xx / timeout / connection error | Backoff of 1, 2, then 4 s; then `SourceUnavailable` |
| 402 | `CreditsExhausted` |
| 401 / 403 | `CrustdataAuthError` |
| 400 | `CrustdataBadRequest` with the error body |

**Rate limiting in the client:** a per-endpoint limit per minute, from the handbook
(search 30, enrich 15, web 10, watch 10), so we stay under the limits instead of
relying on 429s.

**Credits:** if the response carries a cost (check the docs' usage and pricing pages
for the field or header name), use it. Otherwise estimate from the pricing table
(e.g. search = 0.03 × results), and set `credits_estimated=true` in the ledger.

### `WebClient`

Same behaviour as the Crustdata client.
- `search(query, sources, site?, start_date?, end_date?, page=1, location?)` →
  `/web/search/live`
- `fetch(url, human_mode=False)` → `/web/enrich/live`

Each result is recorded with `kind` set to `web` or `news`, and its URL.

### `LLMClient(settings, recorder)`

- **`extract(schema: type[T], system, prompt, model=None) -> T`**
  - Forces a single tool call whose input schema is `schema.model_json_schema()`,
    then validates it with Pydantic.
  - Retries once with the validation error included in the prompt.
  - Records input and output tokens in the ledger.
- **`write(system, prompt, model=None) -> str`** for prose (the memo and outreach).
- **`quote_check(haystack, quote) -> bool`** normalises both sides (whitespace,
  curly quotes and dashes, case), then checks for a substring.
- A `FakeLLM` for tests returns queued responses.
- Read the `claude-api` skill before writing it, and use the models from settings.

### Fixtures

- One JSON file per endpoint, shaped from the docs' examples, each with
  `"_note": "shape from docs example; not live data"`.
- Fixed values used by later phases: a fund with 6 rounds (2 naming "Accel", 1
  "Accel-KKR"); a company with headcount over time; a founder with BITS education.

### Tests

- retry on 429 with the reset header
- give up after repeated 5xx
- 402 raises
- a cache hit spends nothing
- `request_hash` is stable when key order changes
- the rate limiter delays the 31st call within a minute (using an injected clock)
- `quote_check` cases
- `extract` validates and retries once

---

## Merge order and the testable result

1. **13:35** The integrator commits `models/enums.py` + the base type map, then starts
   0B and 0C in their own worktrees.
2. **13:35–14:05** The integrator builds 0A: models, migration, conftest, jobs,
   worker, runs routes, settings, dependencies, Make targets, compose `worker`
   service.
3. **~14:05** Merge 0A, then 0B (include its routers in `main.py`), then 0C. Re-run
   `make check`.
4. **14:15** `make openapi` → hand `docs/api/` to the frontend team. Open the PR to
   `main`.

**Phase 0 is done when:**
- `make check` passes (flake8, mypy strict, pytest, frontend unchanged).
- The migration applies cleanly to the test DB, and `alembic check` shows nothing pending.
- `/docs` shows every route. Stubs return `501` in the error format; `/healthz` and
  `/runs/*` work.
- `make worker` + the test handler: kill the worker after step 1, restart it, and the
  run finishes without repeating step 1 (automated test).
- The client tests pass with no network.

## Risks

- **Contract and tables drifting apart:** both import `models/enums.py`. The
  integrator reviews the 0B schemas against the tables before merging.
- **Contract churn after the handoff:** later changes may only add things. Any
  breaking change needs a re-export and a note to the frontend team.
- **Schema too large to review in time:** the migration is generated automatically,
  then checked against this table list. Only constraints and indexes are adjusted
  by hand.
