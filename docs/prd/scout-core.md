# PRD: Scout, startup scouting and diligence for VC firms

Status: draft, 22 Nov 2026 (ContextCon 05). "Scout" is a working name.
Companion specs:
- [`scout-onboarding-thesis.md`](scout-onboarding-thesis.md)
- [`scout-scoring-actions.md`](scout-scoring-actions.md)
- [`scout-dd-loop.md`](scout-dd-loop.md)

## Problem

VC firms pay scouts, analysts and data tools to do three jobs:

1. Find startups that fit the fund before they raise.
2. Test what founders claim before the second meeting.
3. Keep watching the companies they passed on.

Today an analyst does this by hand, across LinkedIn, news, grant lists, decks and
email. The work is slow, it misses things, and it rarely records where a fact came
from.

## What Scout does

A partner signs in with their LinkedIn, or their name and firm. From the partner's
own profile, the firm and the firm's recent deals, Scout works out two things:

- the firm's investment thesis
- a scoring profile for this VC: which criteria matter and how much

The partner confirms both. They then ask in plain language, for example:

> "BITSian startups building in deeptech that received government grants in the last 6 months"

Scout returns a ranked shortlist. Each startup comes with:

- a score per criterion, built from cited facts
- strong signals, red flags and the gaps it couldn't fill
- a suggested next action

From there Scout carries on with no one at the keyboard:

- It drafts outreach, which the partner approves.
- It requests the deck and data room by email, then ingests and verifies them.
- It re-scores each startup and writes the investment memo when the decision is "invest".
- It keeps watching the companies the partner chose to watch or passed on.

**Handbook themes:**
- Investing 2.1 "Pre-Round Scout" (discovery, thesis fit)
- Investing 2.2 "Diligence Desk" (every deck claim tested)

## Users

- **Partner or associate at a VC firm** (primary). Runs searches, approves anything
  that goes out, decides.
- **Founder** (secondary). Receives outreach and replies with materials by email.

## Principles

1. **Every fact has a source.** A fact records where it came from (an API field path,
   or a page and quote), when it was retrieved, and when it was true (`as_of`).
   When there is no source, Scout says "can't verify" and names what's missing.
2. **Facts and claims are separate.** A fact comes from an independent source. A
   claim is something the founder says. A claim counts as verified only when a
   fact confirms it.
3. **Decisions are computed, not generated.** Scores and suggested actions come from
   deterministic code over stored facts and an editable scoring profile. The LLM is
   used for only four jobs, each with a check:
   - turning the query into structured filters (checked against Crustdata autocomplete)
   - pulling facts and claims out of documents (the quote must be found in the source)
   - drafting outreach and questions (each tied to a fact or a gap)
   - writing the memo (every number is checked against the facts it cites)
4. **A person approves anything irreversible.** That covers sending email,
   marking a startup "invest" and passing on a startup.
5. **Every run has limits.** Each run has a credit limit and a time limit, and
   records every Crustdata and LLM call in a ledger. A run survives a crash and
   resumes where it stopped. Every send happens exactly once.
6. **Everything is adjustable without code changes.** The thesis, scoring weights,
   action thresholds, parsed search filters and source reliability tiers are all data.

## Startup statuses

```
new → shortlist → in_dd → invest | watch | pass
                    ↑  ↺ (another request round, max 2)
watch ──(new progress)──┘      pass ──(pivot / major change)──→ watch
```

| Status | Meaning | Who moves it here |
|---|---|---|
| `new` | Found by a search and scored | Scout |
| `shortlist` | Worth pursuing | Partner (Scout suggests) |
| `in_dd` | Due diligence: data requested from the founder, then ingested and verified. Stages are in `scout-dd-loop.md`. | Partner approves the outreach |
| `invest` | Recommended to invest; the memo is generated | Partner |
| `watch` | Not yet. Scout tracks the company and suggests the next action when something changes. | Partner, or a DD timeout |
| `pass` | Doesn't fit. Scout still tracks it for pivots or major changes. | Partner |

## Main flows

1. **Onboarding:**
   1. LinkedIn, or name + firm → "Is this you?"
   2. The firm → confirm which investor record is the firm.
   3. Recent deals → an inferred thesis and a derived scoring profile, each with
      its evidence.
   4. The partner edits and confirms.
   5. Connect Gmail (optional; uploads work without it).
   
   See `scout-onboarding-thesis.md` and `scout-scoring-actions.md`.
2. **Search:**
   1. The plain-language query is turned into structured filters, shown to the
      partner as editable chips. Every value is checked against Crustdata
      autocomplete.
   2. Scout finds candidates two ways, merged and de-duplicated by Crustdata id:
      - People route: founders matching the people filters (e.g. school) → their companies.
      - Company route: companies matching the industry filters → their founders.
   3. It collects facts on each candidate, scores them and suggests an action. See
      `scout-scoring-actions.md`.
3. **Candidate review:**
   - score breakdown, with the source behind each fact
   - signals, red flags and gaps
   - follow-up questions
   - outreach draft
4. **Due diligence (`in_dd`):**
   1. Scout lists what's missing.
   2. A request email is sent from the partner's Gmail after approval.
   3. The founder's reply is processed: attachments and links are ingested.
   4. Claims are verified and the startup is re-scored.
   
   See `scout-dd-loop.md`.
5. **Decision:**
   - `invest` generates the memo.
   - `watch` and `pass` create a Crustdata watch.
6. **Watching:**
   - Watch events come in by webhook, or from a manual "re-check now".
   - Scout works out what changed, re-scores, and suggests an action.

## External data (Crustdata)

Required headers on every call: `authorization: Bearer <key>` and `x-api-version: 2025-11-01`.

| Use | Endpoint | Approximate credits |
|---|---|---|
| Partner profile | `person/enrich` (LinkedIn URL) | 1–9 |
| Firm, portfolio and deals | `company/identify`, `company/search` filtered on `funding.investors`, `company/enrich` reading `funding.milestones` and `investors_detailed` | 0.2 + ~0.4 per result + 2–4 each |
| Founder discovery | `person/search` (e.g. `education.schools.school` + founder titles); exact values from autocomplete (free) | 0.03 + premium fields, per result |
| Company discovery | `company/search` (semantic mode for concepts like "deeptech") | 0.03 + premium fields, per result |
| Company facts | `company/enrich`: funding, headcount (over time), hiring, people.founders, news, web_traffic, competitors | 2–4 |
| Founder facts | `person/enrich`: dated career history, education | 1–9 |
| Grants, news, public decks | `web/search/live` (sources `news`/`web`, `site:`, `start_date`), `web/enrich/live` (fetch) | 1 per page |
| Partner's own deals | `social_post/search` (the partner as author, investment keywords) | 0.5 per post |
| Tracking | `watch/company` entity watcher (default 30-day refresh) + test notification | 5 per changed company |

**Budget:** onboarding ≈ 60–110 credits; a search ≈ 130 credits for about 30
candidates. Every run has a credit limit. Responses are cached by request hash, so
a retry never pays twice.

## Architecture

The existing scaffold stack: FastAPI, sync SQLAlchemy on Postgres, Alembic, Mongo,
Vite and React. The request path is unchanged: `/api` is proxied to the backend.

- **Postgres** holds everything structured (schema below).
- **Mongo** holds every raw API response, fetched page, parsed document page and
  email body. These are never modified, so any fact can be traced back to exactly
  what was received.
- **Worker:** a separate process (`python -m app.worker`, same image) claims jobs
  from a Postgres `job` table using `FOR UPDATE SKIP LOCKED`. Jobs are idempotent
  and resume from their saved step.
- **Progress** reaches the browser over SSE (`GET /runs/{id}/events`). No websockets.
- **LLM:** the Anthropic API (`claude-sonnet-5-5` for extraction, parsing and the
  memo; `claude-haiku-5-5` for classification), with structured output through tool
  use. It's limited to the four jobs in the principles above.
- **Auth (shortcut):** no login for the hackathon. After onboarding, requests carry
  `X-Investor-Id`. Upgrade to real sessions after the hackathon.
- **Layers:**
  - `routes/` handles HTTP.
  - `services/` holds the logic.
  - `repositories/` handles database access.
  - `schemas/` holds request and response models.
  - `integrations/` holds the Crustdata, web, Gmail and LLM clients.

### Data model (Postgres)

Core tables are listed here; the companion specs add their own.

| Table | Key fields |
|---|---|
| `investor` | name, linkedin_url, crustdata_person_id, fund_id, role |
| `fund` | name, crustdata_company_id, domain |
| `fund_alias` | fund_id, permalink, canonical_name, confirmed_by, confirmed_at, source_id (see the onboarding spec) |
| `deal` | fund_id, company_id, round_date, round_type, amount_usd, led, match_rule, match_evidence, championed_by_investor_id, source_id |
| `thesis` | fund_id, version, status (`draft`/`confirmed`), window, deal_count, confidence, points (each with deal_ids) |
| `scoring_profile` | investor_id, thesis_id, version, origin (`derived`/`edited`/`generic`), confidence, criteria, thresholds, self_reported_weight, source_tiers, derivation (each change with its reason and evidence ids) |
| `search` | investor_id, query_text, parsed_filters, as_of (nullable), status |
| `job`, `run`, `run_step` | kind, payload, status, idempotency_key, attempts, credit_ceiling, deadline, step checkpoints |
| `ledger` | run_id, provider, endpoint, credits_or_tokens, request_hash, source_id |
| `company` / `person` / `company_person` | crustdata ids (unique), name, domain or linkedin_url, role |
| `source` | kind (`crustdata`/`web`/`news`/`email`/`upload`), endpoint_or_url, request_hash, retrieved_at, mongo_ref, reliability_tier |
| `fact` | subject_type, subject_id, predicate, value, as_of, observed_at, source_id, locator (field path, or page + quote), extracted_by (`rule`/`llm`) |
| `candidate` | search_id, company_id, status, dd_stage, score, completeness, breakdown, profile_version, suggested_action |
| `signal` | candidate_id, kind (`strong`/`red_flag`/`gap`), text, fact_ids, claim_ids |
| `question` | candidate_id, text, motivated_by, status (`draft`/`approved`/`sent`/`answered`) |
| `outreach` | candidate_id, channel, subject, body, status (`draft`/`approved`/`sending`/`sent`/`replied`), idempotency_key, approved_by, gmail_message_id |
| `memo` | candidate_id, version, markdown with `[f:id]` and `[c:id]` citations, generated_at |
| `score_snapshot` | candidate_id, score, completeness, breakdown, profile_version, trigger |
| `watch`, `watch_event` | company_id, crustdata_watch_id, reason · payload source_id, what changed, suggested_action, status |

### Routes (backend paths, no `/api` prefix)

```
POST /investors/onboard {linkedin_url} | {name, firm}  → candidate people to confirm
POST /investors/{id}/confirm-identity             → run_id (deals, thesis, profile)
GET  /investors/{id}
GET  /funds/{id}/alias-candidates · POST /funds/{id}/aliases   (confirm the firm's investor record)
GET  /theses/{id} · PUT /theses/{id} · POST /theses/{id}/confirm
GET  /scoring-profiles/{id} · PUT /scoring-profiles/{id}

POST /searches {query, as_of?}                  → parsed filters to confirm
PUT  /searches/{id}/filters · POST /searches/{id}/run   → run_id
GET  /searches/{id}                             ranked candidates

GET  /candidates/{id}                           facts, claims, breakdown, signals, questions, score history
POST /candidates/{id}/status {shortlist|watch|pass|invest}
POST /candidates/{id}/rescore
POST /candidates/{id}/outreach · POST /outreach/{id}/approve · POST /outreach/{id}/send
POST /candidates/{id}/memo · GET /memos/{id}

GET  /sources/{id}                              raw snapshot + the locator used
GET  /runs/{id} · GET /runs/{id}/events (SSE)   progress + ledger

POST /webhooks/crustdata/watch                  shared-secret check
GET  /watch-events?status=open · POST /candidates/{id}/recheck
```

The DD and Gmail routes are in `scout-dd-loop.md`.

## Frontend

**Built by a separate frontend team** against the API contract:
- `docs/api/openapi.json`, regenerated with `make openapi`
- `docs/api/README.md`: flows, call order, the auth header, SSE events and status diagrams

The backend publishes the contract first, with stub routes, so both sides work in
parallel. The pages below are the intended product behaviour.

1. **Onboarding:**
   - LinkedIn, or name + firm, then "Is this you?"
   - live progress
   - "Which of these is your firm?" (choose the investor record)
   - the inferred thesis with the deals behind each point, editable before confirming
   - the derived scoring profile as sliders, each with its reason and evidence, editable before confirming
   - "Connect Gmail"
2. **Search:**
   - the plain-language box
   - the parsed filters as editable chips
   - a run panel showing live steps and credits spent
   - a ranked table with score, completeness, suggested action, flags and status
3. **Candidate page:**
   - **Overview:** score bars per criterion. Hovering a fact shows its source,
     quote and date. Also signals, red flags and gaps.
   - **DD:** the checklist, claims with verification badges, contradictions shown
     side by side with both sources, the email thread, and the score history.
   - **Outreach:** the draft, with Approve and Send.
   - **Memo:** shown for `invest`.
4. **Pipeline:** columns for shortlist, in_dd, watch, pass and invest, plus a feed of
   watch events with suggested actions.
5. **Settings:** scoring weights and rules, action thresholds, source tiers, thesis
   versions, and the Gmail connection.

## Requirements from the judging criteria

| Criterion | How Scout meets it |
|---|---|
| End-to-end (25) | Query → shortlist → approved outreach → founder reply ingested → verified → re-scored → memo. The partner only approves and decides. |
| Facts and verification (20) | Every fact and claim carries a source and an `as_of` date. Facts and claims are kept separate. Contradictions are shown with both sources. The firm is identified by investor permalink, not by name. People and companies are identified by Crustdata id. |
| Robustness (20) | Resumable jobs. Exactly-once sending (a custom header plus a Sent-folder check). Each email message processed once. Re-uploaded documents skipped by hash. 429s retried with backoff. A source that times out puts the job on hold instead of counting as "no result". Credit and time limits. |
| Customer value (20) | Covers the scout and the analyst: thesis fit, plus diligence before the second meeting |
| Demo (15) | The hardest cases on screen: choosing the right "Accel", and a deck claim contradicted by Crustdata |

## Privacy

- Founders' personal data is limited to what the decision needs: professional
  history, plus the contact used for outreach.
- Data room files stay in the fund's own storage and are sent only to the LLM for
  extraction.
- Gmail processing is limited to threads Scout started (see the DD spec).
- Test sends only ever go to team members playing founders.

## Scope

**Must, for the demo (code freeze 6 PM, 22 Nov 2026):**
1. Crustdata client with source, fact and ledger bookkeeping; the facts mapper
2. Onboarding, choosing the firm's investor record, thesis inference and confirmation
3. One search route (founders + company), with grant checks via web search
4. Scoring, suggested actions, signals and questions
5. Candidate page with sources
6. Outreach approval and sending (Gmail, or copy-paste as the fallback)
7. The DD loop with VC upload; PDF ingestion; verifying headcount, funding and founder background; re-scoring with history
8. The memo for `invest`
9. Watch: create one, receive the test notification, suggest an action

**Stretch:**
- automatic Gmail reply processing
- the founder upload page
- XLSX data rooms
- reminders
- replaying a search as of a past date (the schema already supports it through `fact.as_of`)

**Later:**
- tracking pivots of passed companies in depth
- calendar booking
- several partners per fund, with roles
- a dedicated inbound email address

## Open questions

- **Scoring parameters:** derived per VC from their profile, the firm and its recent
  trend (rules v1; calibration against peers is a stretch goal). Still open: whether
  the rule thresholds in `profile_rules.json` match how VCs actually weigh things.
  Sanity-check with a real partner if possible.
- **Indian seed coverage in `funding.milestones`:** unverified until one real
  onboarding call. The fallback is that the partner confirms or adds deals, and a
  thin portfolio is labelled "low confidence".
- **Government grant coverage:** expected to be weak in Crustdata funding data.
  Grants come from web search, and many will be "can't verify".
