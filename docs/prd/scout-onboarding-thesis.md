# Spec: onboarding and thesis inference

Part of [`scout-core.md`](scout-core.md). Status: draft, 22 Nov 2026.

## Goal

From who the partner is, produce two drafts, each citing the evidence behind
every point:

1. A **draft investment thesis**, based on the firm's verified recent deals.
2. A **draft scoring profile** (criteria, weights, rule parameters), based on the
   partner's own profile, the firm, and its recent investment trend.

The partner edits and confirms both before any search uses them.

## Identifying the partner

The partner gives either of these:

- **A LinkedIn URL** → `person/enrich` directly.
- **Their name and the firm they work at** → `company/identify` on the firm, then
  `person/search` filtered on the name and current employer.
  - One match is used directly.
  - Several matches (people with the same name) are shown as a choice, with title,
    location and photo-free summaries. The partner picks themselves.
  - No match: we ask for the LinkedIn URL.

Either way, the partner confirms "Is this you?" before anything else runs. This
keeps the thesis from being built on someone else with the same name.

## Flow

| Step | Call | Output |
|---|---|---|
| 1. Partner | `person/enrich` (LinkedIn URL, or the confirmed match from name + firm) | `investor`: current employer (`crustdata_company_id`), title, dated career history, as facts |
| 2. Firm | `company/enrich` on that employer | `fund`: official name, domain, description |
| 3. Firm's investor record | Name matching (below) | Confirmed `fund_alias` rows, each with a Crunchbase permalink and its exact name |
| 4. Candidate portfolio | `company/search` on `funding.investors` for each confirmed name, optionally with `funding.last_fundraise_date` inside the window | Companies the firm has backed at some point |
| 5. Deals | `company/enrich` (funding, headcount, taxonomy) on each candidate | `deal` rows for rounds that name the firm (strict matching, below) |
| 6. The partner's own deals | `social_post/search`: the partner as author, keywords like "backed", "invested", "welcome to the portfolio" | `deal.championed_by_investor_id` where a post names a portfolio company |
| 7. Thesis | Counts computed in code (below) | `thesis` v1, `draft` |
| 8. Scoring profile | Derivation rules over the deals at entry, the trend and the partner's career ([scoring spec](scout-scoring-actions.md#deriving-the-profile-onboarding)) | `scoring_profile` v1, `derived` (or `generic` when the evidence is thin), each change with its reason and evidence |
| 9. Confirm | The partner edits and confirms the thesis and the profile (sliders, each with its reason) | `thesis` `confirmed`, `scoring_profile` confirmed |

**Window:** the last 18 months by default. "Recent trend" compares the last 6
months with the 12 months before.

## Firm name matching

**Why it's needed:** `funding.investors` and each round's `investors` are plain name
strings.
- "Accel" is a substring of "Accel-KKR", and "Accel India" is a different investor record.
- Firms rebrand: Peak XV Partners appears as "Sequoia Capital India" on rounds before 2023.

Matching on names alone attributes deals to the wrong firm.

1. **Name variants.**
   - The official name, plus the name without suffixes ("Ventures", "Capital",
     "Partners", "Fund", "LLP", "Advisors").
   - The domain stem (`accel.com` → `accel`).
2. **Candidate investor records.**
   - Run `company/search` on `funding.investors` for each variant (≤ 25 results)
     and enrich a handful of the matches.
   - Collect the `funding.investors_detailed` entries whose names are similar.
   - Group them by Crunchbase `permalink`. Each group gets a label and 3 example
     portfolio companies.
3. **The partner confirms** ("Which of these is your firm? Select all that apply").
   - A single exact match is pre-selected.
   - Multi-select covers rebrands and separate fund vehicles.
   - Store a `fund_alias` (permalink, canonical_name, confirmed_by, confirmed_at, source_id).
4. **Strict round matching.** A round becomes a `deal` only if both hold:
   - the company's `investors_detailed` contains a confirmed permalink, **and**
   - the round's `investors` string, split into individual names, contains an
     entry **equal** to that permalink's canonical name after normalising
     (lowercase, collapsed spaces, "(lead)"-style notes removed). Contains is not
     enough.
   
   Store `match_rule = "exact_round_name"` and `match_evidence` (which round
   string matched which canonical name).
5. **Unclear cases are labelled, not guessed.**
   - The firm is on the company but no round names it: the company counts as
     "portfolio, date unknown". It's left out of trends and flagged.
   - One name appears under two confirmed permalinks: the round is held for review.

## Thesis inference (deterministic)

For each deal, record the following **at the time of the deal**, each as a fact
with an `as_of` date:

- sector (taxonomy and industries)
- stage (`round_type`)
- check size (`amount_usd`) and whether the firm led
- HQ location
- company age
- headcount at the round date (from headcount over time)

Then compute these thesis points:

| Point | Computation |
|---|---|
| Sectors | Share of deals per sector; the top sectors cover ≥ 70% of deals |
| Stage | Share of deals per round type |
| Check size and lead | Median and range of round amounts, and the share of deals the firm led |
| Geography | Share by country and city |
| Company profile at entry | Median age and headcount at the round date |
| Trend | The last 6 months compared with the 12 months before, per sector and stage. A shift is reported only if it involves ≥ 3 deals. |
| The partner's lens | Sectors and stages of the deals the partner championed, plus the sectors they worked in before |

- Every point stores the `deal_ids` behind it and shows them as citations.
- **Confidence:** `high` with ≥ 10 deals in the window, `medium` with 5–9, `low`
  with < 5. With low confidence the window widens to 36 months and the thesis is
  shown with a warning. The partner is asked to confirm or add deals.
- The LLM writes only the summary paragraph, from the computed points. Any number
  it writes must exist in those points.

## Partner edits

The partner can add or remove sectors, stages, geographies and check size, set
exclusions, and add deals Scout missed (each with a URL as its source).

- Each save creates a new `thesis` version.
- Searches record which thesis version they used.

## Edge cases and tests

- Accel vs Accel-KKR vs Accel India: only the confirmed permalink's deals are counted.
- Peak XV plus its old Sequoia India name: both names are confirmed, and deals from
  both count.
- A round string with "(lead)", extra spaces or different capitals: it matches.
- The firm is on the company but not on any round: "date unknown", left out of trends.
- The partner's employer isn't an investor (e.g. a corporate venture arm with no
  `investors_detailed` entries): low confidence, and the partner is asked to add deals.
- The LinkedIn URL doesn't resolve to a person: say so and ask for name + firm instead.
- Name + firm matches two people: show both and let the partner pick; never auto-pick.
- The partner recently changed firms (current employer started < 3 months ago): use
  the new firm's deals for the thesis. The partner's past deals at the old firm feed
  only the "partner lens" part of the profile, and this is labelled.

All of these run as unit tests on fixed data, with no credits spent.

## Schema added

`fund_alias`, `deal`, and `thesis` (see the core PRD). There's also
`investor_post_link` (investor_id, social post source_id, company_id), which
backs `deal.championed_by_investor_id`.
