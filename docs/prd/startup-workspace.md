# PRD: Multiplayer startup workspace

Status: draft, 22 Nov 2026 (ContextCon 05, BITS Pilani). Product name TBD.

## Problem

Early-stage founders do jobs that established companies pay firms for:

- **Grant consultants** find grants, check eligibility and fill applications, for a retainer or a 2–5% success fee.
- **Fundraising advisors** build investor lists and warm outreach.
- **Market research and marketing agencies** track competitors and trends and turn them into content.

Founders do this between everything else. The context they need is split across their own files (the deck, the financials, notes) and the outside world (portals, news, social posts, funding records). A chatbot has neither, and gets dates and facts wrong with confidence.

## What we build

A shared workspace where a startup team's agents turn a request into **finished work the team reviews and copies out**:

- a grant application, every field answered
- an outreach message tied to someone's recent post
- a ready-to-publish post

Every fact cites its source and date. Anything that can't be taken back (submitting, sending, posting) stays with a person.

### Users

A founding team of 1–5 people working in the same workspace at the same time. Each one sees the others' presence and edits, and approves drafts.

## Core loop (shared by every flow)

```
find → check → draft with sources → team review → copy out
```

1. **Find:** pull candidates from external sources (Crustdata, web, portals).
2. **Check:** test each candidate against the team's internal context. Each check results in `met`, `not met`, or `missing` (can't verify, and names what's needed).
3. **Draft:** produce the deliverable. Every claim links to a source (URL or API field, plus the date retrieved).
4. **Team review:** teammates edit in real time, field by field. One person approves.
5. **Copy out:** a copy button per field. Nothing is submitted, sent or posted by the system.

Each domain plugs into this loop. A new domain later means another flow, not a new system.

## Domains

Six areas of a startup's work. Each runs on the core loop and ends in a
deliverable. Some steps are shared, such as outreach drafts (used by 2, 4 and
5) and the change feed (6, which feeds all the others), and each is built once.

### 1. Market research

**Request:** "Who are we really up against, and where's our moat?"

- **Find:**
  - Company Search for similar companies (industry, taxonomy, keywords).
  - Company Enrich `competitors` on our own company and on each competitor
    found, to widen the list.
- **Gather signals per competitor:**
  - Company Enrich: `funding`, `headcount` (including by function), `hiring`,
    `news`, `public_launches`, `technographics`, `web_traffic`.
  - Job Search with aggregations by role (e.g. 5 new ML roles).
- **Check:** compare against our own product and positioning, taken from
  internal context.
- **Draft:** a competitor brief.
  - One card per competitor: what they do, money raised, team growth, and
    where they're heading.
  - "Where they're heading" is marked as an **inference** and cites its
    evidence, e.g. "hiring 5 ML engineers since October suggests in-house
    models".
  - Then a moat map: where we overlap, and where we're different.

### 2. Market validation

**Request:** "Find 20 people we should talk to this week to validate the problem."

- **Find:**
  - Person Search on the ideal-customer profile (title, seniority, company
    size and industry).
  - `social_post/search` for people posting about the problem in the last 30
    days, which signals pain.
  - Startup-ecosystem voices, sorted by engagement.
- **Check:** each person must match the profile, with a recent signal
  preferred. Leave out anyone already contacted.
- **Draft:**
  - The list, with the reason each person was picked, citing their post or
    profile.
  - An outreach draft per person (the shared outreach step).
  - An interview script built from the startup's open questions.

### 3. GTM

**Request:** "Who exactly do we sell to first, and what's the plan?"

- **Find:**
  - Profile segments sized with free `limit: 0` counts (Person/Company Search).
  - Where each segment is active and what it talks about (`social_post/search`
    by author profile).
  - Trends from news and forums (`web/search`).
- **Check:** keep the segments where internal context (product, pricing,
  traction) shows a fit.
- **Draft:** a GTM plan.
  - Ranked target segments, with sizes and sources.
  - Messaging per segment.
  - Channels.
  - A content calendar: next-post suggestions with a "why now" for each,
    founder-voice drafts, and comments to leave on influencer posts.

### 4. Fundraising

**Request:** "Which grants, accelerators and investors fit us this month?"

- **Grants (demo flow):**
  1. `web/search` with `site:` limited to known portals (Startup India, BIRAC,
     state startup missions, MeitY), then `web/fetch` each grant page. Extract
     the deadline, eligibility rules, questions and character limits.
  2. Check each rule against the company's facts: `met`, `not met`, or
     `missing`.
  3. Draft a document that mirrors the form, every field filled, labelled
     `drafted`, `needs input` or `can't verify`, and within the form's limits.
- **Accelerators:**
  - `web/search` (`news`) and `social_post/search` for "applications open"
    and "cohort" posts.
  - Output: deadlines and eligibility, checked the same way, plus draft answers
    for the application.
- **Investors:**
  - Company Enrich `funding.investors` on 10–20 comparable startups, then
    Person Search for the partners.
  - Rank by stage and sector fit, plus recent activity (posts and new deals).
  - Output: an outreach draft per investor.
- **Edge cases:**
  - The same grant found on two sites becomes one record.
  - A changed deadline is flagged.
  - A form behind a login asks the team to upload it.

### 5. Networking

**Request:** "Find us mentors, early testers and people who can refer us."

- **Find:**
  - *Mentors:* Person Search for founders and operators who've built in our
    space (past employers in the sector, founder titles, exits).
  - *Early testers:* the market-validation list, filtered to the people with
    the strongest signals.
  - *Referrals:* people who share a school or employer with a team member.
    Use Person Enrich on the team and match education and past employers.
- **Check:**
  - A shared background must be real, citing both people's profiles.
  - Crustdata doesn't provide connection lists, so we never claim "you're
    connected".
- **Draft:** a ranked list with the shared ground for each person, plus an
  outreach draft that leads with it.

### 6. Change feed (watchers)

**Request:** "What changed in our space this week, and what should we do?"

- **Watch:**
  - Competitors and related companies: funding rounds, IPOs, headcount moves,
    launches and news.
  - Key people (competitor leaders, investors, mentors): job changes and new
    posts.
  - Industry keywords: new posts and news.
- **Now:** an hourly job re-runs the searches and keeps only results newer than
  the last run. Later, Crustdata Watchers on a 30-day refresh (see
  `docs/todos.md`).
- **Draft:**
  - A weekly digest: what changed, the source, and **what to do about it**.
    Each item links to the area it affects, e.g. "competitor hired an ML
    lead → update the competitor brief" or "investor X posted about our
    space → outreach draft ready".
  - Changes also update the memory graph, so the other areas always work from
    current facts.

### Shared outreach step (used by 2, 4, 5)

- **Trigger required:** a recent post (last 30 days), a job change, or a shared
  background. The draft quotes and links it. No trigger means no draft.
- **Two versions:** a LinkedIn note (≤ 300 characters) and an email. Content:
  the hook, one real overlap from internal context, and a specific ask.
- **Never twice:** never draft twice for the same person and trigger.
- **Contact details:** the person's LinkedIn link by default. Look up contact
  details (Contact Enrich) only for people the team has approved.

## Context layers

- **Internal context:**
  - RAG over uploaded files (deck, financials, notes).
  - An A-Mem style memory graph: atomic notes with keywords, tags and embeddings, linked by the LLM.
- **External context:** Crustdata (Company, Person, Job, Social Post, Web), refreshed by an hourly job. Watchers come later; see `docs/todos.md`.
- **Rules for memory:**
  - Source notes are never rewritten. Each one keeps its source (URL or API field) and the date retrieved.
  - LLM-made links and summaries are separate notes, marked as derived.
  - Companies and people are keyed by `crustdata_company_id` / `crustdata_person_id`, so one entity under two names stays one record.

## Multiplayer

- Shared presence: cursors and who's online, per workspace.
- Field-level editing locks on drafts: one editor per field at a time. Others see a live preview of the text being typed.
- Approval is a durable write that records who approved what and when, broadcast to everyone.
- Run progress (found / checked / drafted) streams to every connected teammate.

## Requirements from the judging criteria

| Requirement | How |
|---|---|
| End-to-end, no one steps in | Each flow ends in a finished draft. People only review, approve, and supply `missing` facts. |
| A source for every claim | Every field and claim links to a record with its date. "Can't verify" names what's missing. |
| A person approves the irreversible | Nothing is submitted, sent or posted automatically. Every draft needs an approval. |
| Ceiling on every run | A time limit and credit limit per run. Every Crustdata and model call goes into a ledger table. |
| Survives a crash or timeout | Runs save their progress step by step and resume. Each run and each draft has a unique key, so neither happens twice. 429s are retried with backoff, and a silent source is held, never read as "no result". |

## Out of scope (for the hackathon)

- Automatic form submission, sending messages, and posting (see `docs/todos.md`).
- Crustdata Watchers and month-over-month sentiment analysis (see `docs/todos.md`).
- Hiring and financials tracking.
- Building all six domains end to end. The demo runs Fundraising → Grants in full; the others run as far as time allows.
- Orgs, projects, roles and invite links (Kith's multi-tenant model). For now there is one workspace per team, shared by link.

## Success for the demo

- A grant request the system hasn't seen goes in, and a filled-in application document comes out in under 2 minutes.
- Every field has a source or is marked `needs input` / `can't verify`.
- A teammate edits and approves live on screen.
- The demo also shows a duplicate grant merged, a restart mid-run that resumes without duplicating anything, and the credit ledger for the run.
