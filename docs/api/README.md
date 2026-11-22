# Scout API contract

The frontend builds against this. The full spec, with a request/response example on
every model, is [`openapi.json`](openapi.json); the same thing is browsable at
<http://localhost:8000/docs> under `make dev` (use "Authorize" to set `X-Investor-Id`).

**Phase 0 status:** every route below exists with its final shapes, but returns
`501 not_implemented` until its phase lands. `GET /healthz` works.

Regenerate the spec after changing schemas or routes: `make openapi` (from the repo root).

## Basics

| | |
|---|---|
| Base URL | `/api` (nginx / the Vite proxy strips it: `/api/searches` → backend `/searches`) |
| Auth | Header `X-Investor-Id: <uuid>` on every call **except** `POST /investors/onboard`, `GET /healthz`, `POST /webhooks/crustdata/watch`, `GET /integrations/gmail/callback`. You get the id from `POST /investors/onboard`; keep it (e.g. localStorage). |
| JSON | snake_case fields |
| Ids | uuid strings, except fact and ledger ids, which are integers |
| Timestamps | ISO-8601, UTC (`2026-11-21T10:00:00Z`); dates are `YYYY-MM-DD` |
| Lists | `?limit=` (default 50, max 200) and `?offset=`; response is `{items, total}` |
| Creates | `201` with the created object |
| Long-running work | `202` with `RunAccepted` (see below) |

## Errors

Every non-2xx response:

```json
{"error": {"code": "not_found", "message": "Candidate not found", "details": {}}}
```

Branch on `code`, show `message`.

| Code | Typical status | Meaning |
|---|---|---|
| `not_found` | 404 | No such object (or not yours) |
| `validation_error` | 422 (400) | Bad body/params; `details.errors` is a list of `{loc, msg, type}` |
| `conflict` | 409 | Wrong state for this action (e.g. editing filters of a search that already ran) |
| `not_allowed` | 401 / 409 | Missing `X-Investor-Id` (401), or a status transition that isn't allowed (409) |
| `upstream_unavailable` | 502/503 | Crustdata, the LLM or Gmail is down; retry later |
| `credits_exhausted` | 402 | The Crustdata account is out of credits |
| `ceiling_reached` | 409 | The run hit its credit ceiling (also shows up as a `held` run) |
| `not_implemented` | 501 | Route not built yet |

## Long-running operations: 202 → SSE → poll

These return `202`:

```json
{"run_id": "a9b8…", "status_url": "/runs/a9b8…", "events_url": "/runs/a9b8…/events"}
```

1. Open `GET /api/runs/{id}/events` (Server-Sent Events). `EventSource` can't send
   headers, so use a fetch-based reader (e.g. `@microsoft/fetch-event-source`) with
   `X-Investor-Id`.
2. Events:

   | Event | `data` | When |
   |---|---|---|
   | `step` | `{"name": "collect_facts", "status": "running" \| "done" \| "failed", "seq": 2}` | A step starts or changes |
   | `run` | `{"status": "queued" \| "running" \| "done" \| "failed" \| "held", "credits_spent": 41.25}` | The run changes |
   | `end` | `{}` | The run is `done`, `failed` or `held`. Close the stream. |

   ```
   event: step
   data: {"name": "collect_facts", "status": "done", "seq": 2}

   event: run
   data: {"status": "done", "credits_spent": 41.25}

   event: end
   data: {}
   ```
3. After `end` (or as a fallback, every 2 s), `GET /api/runs/{id}` → `RunOut`
   (`status`, `steps`, `credits_spent`, `hold_reason`, last 50 `ledger` rows).
   `held` means it needs a person: show `hold_reason` (e.g. credit ceiling reached).
4. Then re-fetch the object the run was working on (investor, search, candidate…).

## Flows

Paths below omit the `/api` prefix. ⏳ = returns `202`, follow the run.

### Onboarding (screens: identify → "Is this you?" → firm records → thesis → profile)

1. `POST /investors/onboard` `{linkedin_url}` or `{name, firm}` → `{investor_id, candidates}`.
   Save `investor_id`; send it as `X-Investor-Id` from now on.
2. `POST /investors/{investor_id}/confirm-identity` `{crustdata_person_id}` ⏳
3. `GET /investors/{investor_id}` → `fund.id`, `onboarding_step`.
4. `GET /funds/{fund_id}/alias-candidates` → checklist (`preselected` ticked).
5. `POST /funds/{fund_id}/aliases` `{permalinks}` ⏳ (deals → thesis → profile)
6. `GET /investors/{investor_id}` → `current_thesis_id`, `current_profile_id`.
7. `GET /theses/{id}`; edits: `PUT /theses/{id}` (returns a **new version, new id**).
8. `GET /scoring-profiles/{id}`; edits: `PUT /scoring-profiles/{id}` (new version, new id).
9. `POST /theses/{id}/confirm` and `POST /scoring-profiles/{id}/confirm`.
10. Optional: Gmail (see below).

`InvestorOut.onboarding_step` tells you where to resume: `confirm_identity`,
`confirm_aliases`, `building_thesis`, `review_thesis`, `review_profile`, `done`.

### Search (screens: query → filter chips → ranked list)

1. `POST /searches` `{query, as_of?}` → `SearchOut` (`status: draft`) with
   `parsed_filters` (chips) and `unresolved` (`{term, suggestions}`).
2. Optional: `PUT /searches/{id}/filters` with the edited `FilterSpec`.
3. `POST /searches/{id}/run` ⏳
4. `GET /searches/{id}` → `candidates`, highest score first.
5. History: `GET /searches`.

`FilterSpec` = `{people: [Condition], companies: [Condition], funding: [Condition],
grants: GrantFilter | null, window_months}`; `Condition` = `{field, op, value,
display}` with `op` in `=`, `in`, `>`, `<`, `contains`, `semantic`. Render `display`;
send the whole object back.

### Candidate review (screen: candidate page)

1. `GET /candidates/{id}` → company, founders, `breakdown` (each `CriterionScore` has
   `score` 0–100 or `"unknown"`, and cited `facts`/`claims`), `signals`, `questions`,
   `suggested_action`, `score_history`.
2. Citation click-through: `GET /sources/{source_id}` → `{citation, raw}`.
3. Decide: `POST /candidates/{id}/status` `{status, reason?}` (409 `not_allowed` if the
   transition isn't allowed).
4. `POST /candidates/{id}/rescore` (sync, no credits) or `POST /candidates/{id}/recheck` ⏳
   (fresh data, spends credits).
5. Memo: `POST /candidates/{id}/memo` ⏳ → `GET /candidates/{id}` → `latest_memo_id` →
   `GET /memos/{id}`.

### Outreach (screen: candidate page, outreach panel)

1. `POST /candidates/{id}/outreach` `{channel: email|linkedin, purpose: call_request|follow_up}` → draft.
2. `PUT /outreach/{id}` `{to_address?, subject?, body?}` while `draft` or `approved`; editing an approved message sends it back to `draft` for re-approval.
3. `POST /outreach/{id}/approve`.
4. `POST /outreach/{id}/send` (Gmail) **or** `POST /outreach/{id}/mark-sent` (sent by hand).

### Due diligence (screen: DD tab)

1. `POST /candidates/{id}/dd` → `DDOut` (candidate goes to `in_dd`; checklist +
   request draft in `request`). Call again for round 2 (max 2 rounds).
2. Edit the request draft with `PUT /outreach/{request.id}`.
3. `POST /dd/{request_id}/approve`, then `POST /dd/{request_id}/send` (Gmail) or
   `POST /dd/{request_id}/mark-sent`.
4. Founder files: arrive by Gmail, or the partner uploads them:
   `POST /candidates/{id}/documents` (multipart: `file`, `kind`) → `DocumentOut` with
   `run_id` ⏳.
5. Poll/refresh `GET /candidates/{id}/dd` for `stage`, `items`, `claims`,
   `verifications`, `thread`, `score_history`.
6. At `ready_for_decision`: decide with `POST /candidates/{id}/status`.

### Watch (screen: watch inbox)

1. `GET /watch-events?status=open` → `{items, total}`.
2. Act (e.g. `POST /candidates/{id}/status`, `POST /candidates/{id}/recheck` ⏳), or
   `POST /watch-events/{id}/dismiss`.

### Gmail (screen: settings)

- `GET /integrations/gmail` → `GmailStatus`.
- `GET /integrations/gmail/connect` → `GmailConnect {auth_url}`; set
  `window.location = auth_url` (a navigation can't carry `X-Investor-Id`, so this
  isn't a redirect). Google returns to `/integrations/gmail/callback`, which
  redirects back to the app.
- `DELETE /integrations/gmail` → `connected: false`.

## Status diagrams

Candidate `status`:

```
new ──► shortlist ──(POST /candidates/{id}/dd)──► in_dd ──► invest
 │          │                                     │  ▲ ↺ round 2
 │          │                                     ├──► watch ──► shortlist / in_dd
 └──────────┴──► watch | pass                     └──► pass ──► watch (pivot)
```

Allowed via `POST /candidates/{id}/status`: `new → shortlist | watch | pass`,
`shortlist → watch | pass`, `in_dd → invest | watch | pass`, `watch → shortlist | pass`,
`pass → watch`. `in_dd` is entered only via `POST /candidates/{id}/dd` (also from
`watch`). `in_dd` also times out to `watch` after 14 days with no reply.

`dd_stage` (only while `in_dd`):

```
gaps_identified → request_drafted → awaiting_founder → ingesting → verifying → ready_for_decision
                   (approve + send)   (reminder at 5 d,                         │
                                       timeout to watch at 14 d)                └─► round 2 → gaps_identified
```

Outreach `status`:

```
draft ──approve──► approved ──send──► sending ──► sent ──► replied
                        └────mark-sent────────────► sent
```

DD item `status`: `requested → received | received_needs_access → verified |
contradicted | unverifiable`.
