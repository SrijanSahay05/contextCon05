# Spec: due diligence loop (`in_dd`) and Gmail

Part of [`scout-core.md`](scout-core.md). Status: draft, 22 Nov 2026.

## Goal

When the public data isn't enough to decide, Scout does the rest:

1. It asks the founder for exactly what's missing.
2. It collects the reply: attachments, links and answers.
3. It verifies every founder claim against independent sources.
4. It re-scores the startup and suggests a decision.

The partner only approves outgoing messages and makes the final call.

## Stages of `in_dd` (`candidate.dd_stage`)

| Stage | What happens | Automatic? |
|---|---|---|
| `gaps_identified` | For each `unknown` or self-reported-only criterion, a `dd_item` is created: deck, data room, financials, cap table, grant letter, customer references, or the answer to a question | Yes |
| `request_drafted` | Outreach draft: a call request, the requested items and the follow-up questions | Drafted automatically; a person approves |
| `awaiting_founder` | Sent through Gmail (or copied by hand as the fallback). After N days (default 5) a reminder is drafted for approval. After M days (default 14) with no reply, the startup moves to `watch`. | Timers automatic, reminders approved by a person |
| `ingesting` | Attachments and public links are parsed; claims are extracted, each with a page and exact quote | Yes |
| `verifying` | Each claim is checked against independent sources | Yes |
| `ready_for_decision` | Re-scored, with what changed and a suggested action. If items are still missing, another request round is allowed (max 2). | Suggested; a person decides |

## Claims vs facts

- A **claim** is something the founder states, in a document or an email answer.
- A **fact** comes from an independent source.
- Claims are extracted by the LLM with `{predicate, value, as_of, page, quote}`. A
  claim is kept only if the quote is found on that page after normalising
  whitespace.

| Claim type | Checked against | Possible results |
|---|---|---|
| Team size, hiring | Company Enrich headcount over time; Job Search | `verified` / `contradicted` |
| Funding raised, investors | `funding.milestones`, using the investor matching rules | `verified` / `contradicted` |
| Founder background | Person Enrich dated career history | `verified` / `contradicted` |
| Grants | `web/search` + `web/enrich/live` (fetch) on grant lists and news, with an exact quote | `verified` / `unverifiable` |
| Customers, partnerships | Web search for named announcements | `verified` / `unverifiable` |
| Revenue, retention, burn | No public source | `self_reported` |

**Tolerance:** a number counts as verified within ±15% when the `as_of` dates are
within 60 days of each other. Both thresholds are configurable. Outside the
tolerance the claim is `contradicted`, and both sources are shown side by side.

## Gmail

**Connection:**
- An OAuth sign-in during onboarding, with two permissions: `gmail.send` and
  `gmail.readonly`.
- The app runs in Google's "testing" mode, with listed test users.
- The refresh token is stored encrypted with `TOKEN_ENCRYPTION_KEY`, using the
  `cryptography` library's symmetric encryption (Fernet).

**Sending (exactly once):**
1. The outreach must be approved. It moves to `sending` with an idempotency key.
2. It's sent through the Gmail REST API (httpx), carrying the header
   `X-Scout-Outreach-Id: <id>`. The message id and `threadId` are stored, and the
   outreach becomes `sent`.
3. **After a crash** with an outreach stuck in `sending`: the worker searches the
   Sent folder for that header. If the message is found, it's marked `sent`.
   Otherwise it's sent again.

**Processing replies:**
- A `poll_gmail` job runs every 60 s and calls `history.list` from the saved
  `historyId`.
- **Only threads in `mail_thread` are processed.** Other mail is never read or stored.
- Each message is processed once (unique on `gmail_message_id`).

| Reply contains | Action | `dd_item` result |
|---|---|---|
| PDF, XLSX or CSV attachment | Classified (deck / financials / cap table / grant letter) using the filename and an LLM read of page 1; then ingested and verified | `received` → `verified` / `contradicted` / `unverifiable` |
| A public link (Drive, Notion, PDF URL) | Fetched with `web/enrich/live`, then ingested | Same as above |
| A gated link (DocSend, a data room with login) | Recorded; the partner is asked to open it | `received_needs_access` |
| Text answers | The LLM matches each answer to a sent question, quoting the founder's words; stored as a self-reported claim and verified where possible | The question becomes `answered` |
| A scheduling request | Shown to the partner (no calendar booking) | — |

**If Gmail isn't connected:** the partner uploads the files the founder sent
(`POST /candidates/{id}/documents`). Everything after ingestion is identical.

## Schema added

| Table | Key fields |
|---|---|
| `dd_request` | candidate_id, round, outreach_id, status, upload_token_hash (stretch), expires_at |
| `dd_item` | dd_request_id, kind, status (`requested`/`received`/`received_needs_access`/`verified`/`contradicted`/`unverifiable`), document_id, satisfied_by_message_id |
| `document` | candidate_id, kind, origin (`email`/`vc_upload`/`founder_upload`/`public`), storage_path, mime, sha256 (unique per candidate), parse_status, source_id |
| `claim` | candidate_id, document_id or message_id, page, quote, predicate, value, as_of |
| `verification` | claim_id, result, fact_ids, note, tolerance_used |
| `mail_account` | investor_id, email, refresh_token_enc, history_id, scopes, status |
| `mail_thread` | dd_request_id, gmail_thread_id |
| `mail_message` | mail_thread_id, gmail_message_id (unique), direction, received_at, processed_at, mongo_ref |

Mongo stores the raw parsed pages per document and the raw email bodies.

## Routes

```
POST /candidates/{id}/dd                    gap analysis → dd_items + request draft
GET  /candidates/{id}/dd                    checklist, claims, verifications, thread, score history
POST /dd/{id}/approve · POST /dd/{id}/send  (Gmail) · POST /dd/{id}/mark-sent (fallback)
POST /candidates/{id}/documents             partner upload
GET  /integrations/gmail/connect · GET /integrations/gmail/callback · DELETE /integrations/gmail
# stretch: founder upload page
GET  /dd/upload/{token} · POST /dd/upload/{token}/files · POST /dd/upload/{token}/answers
```

**Rules for the founder upload page (stretch):**
- The token is single-use per round, expires, and is stored only as a hash.
- File types are on an allow-list (PDF, XLSX, CSV), with a 25 MB size cap.
- Requests are rate-limited.

## Worker jobs

`poll_gmail` → `classify_attachment` → `ingest_document` → `verify_claims` → `rescore`

- Each job is idempotent: it's keyed by `gmail_message_id` or the document's
  `sha256`.
- A failed external call is retried with backoff. After 3 attempts the item is held
  for the partner, never treated as "no data".

## Config (in `Settings` and in `backend/.env.example` as placeholders)

`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `TOKEN_ENCRYPTION_KEY`, `DD_REMINDER_DAYS`, `DD_TIMEOUT_DAYS`

## Safety

- Nothing is sent without approval.
- Test sends only go to team members playing founders.
- Data room files are confidential. They're stored in the fund's own storage and
  sent only to the LLM for extraction.
- The README states that `gmail.readonly` technically covers the whole inbox, and
  that the limit to Scout's own threads is enforced in code.

## Edge cases and tests

- The same deck attached twice is skipped by hash; no duplicate claims.
- A reply on an unrelated thread is ignored.
- A crash while sending is resolved by the Sent-folder check, so there's no second email.
- A deck claims 40 engineers; Crustdata shows 18 as of the same month → `contradicted`,
  a red flag and a follow-up question.
- A grant claim with no public record → `unverifiable`, and the score shows it as a gap.
- A gated DocSend link → `received_needs_access`, and the partner is prompted.
- No reply within the timeout → `watch`, with a Crustdata watch created.

## Demo test case

A deck for a real startup with one deliberately wrong number (headcount).

- It's labelled in the repo as **a test file made by the team**.
- It's sent as a reply from a teammate's address.
- Expected result: the checklist ticks, headcount is `contradicted` with both sources
  shown, the score drops, and a follow-up question is drafted.
