# Spec: scoring, signals and suggested actions

Part of [`scout-core.md`](scout-core.md). Status: draft, 22 Nov 2026.

The scoring parameters are **derived for each VC during onboarding**. They come from:
- the partner's own profile
- the firm
- the firm's recent investment trend

The partner then reviews and confirms them (see "Deriving the profile" below). The
generic weights are used only as a fallback when the evidence is too thin.

## Principles

- Scoring is a pure function: `score(facts, claims, profile) → breakdown`. It's
  deterministic and unit-tested, and makes no API or LLM calls.
- Re-scoring after the partner edits weights, or after new facts arrive, costs no credits.
- **Unknown is not zero.** A criterion with no evidence is reported as `unknown`
  and left out of the weighted score. Completeness is reported separately.
- Evidence weights:

  | Evidence | Weight |
  |---|---|
  | Fact (independent source) | 1.0 |
  | Verified claim | 1.0 |
  | Self-reported claim | `self_reported_weight` (default 0.5) |
  | Contradicted claim | Penalty, plus a red flag |

- Source reliability scales the evidence: tier A (Crustdata, government registries
  and grant lists) = 1.0, tier B (established news) = 0.8, tier C (blogs, social
  posts) = 0.5. The tiers are editable in `profile.source_tiers`.

## Scoring profile (data, editable)

```json
{
  "criteria": [
    {"key": "thesis_fit", "weight": 0.25, "rule": "thesis_match", "params": {}},
    {"key": "team", "weight": 0.20, "rule": "team_signals", "params": {"use_pedigree": false}},
    {"key": "traction", "weight": 0.20, "rule": "growth_signals", "params": {"window_months": 6}},
    {"key": "funding", "weight": 0.10, "rule": "funding_stage_fit", "params": {}},
    {"key": "market", "weight": 0.15, "rule": "market_signals", "params": {}},
    {"key": "momentum", "weight": 0.10, "rule": "recent_events", "params": {"window_months": 6}}
  ],
  "thresholds": {"reach_out": 65, "watch": 45, "min_completeness": 0.5},
  "self_reported_weight": 0.5,
  "source_tiers": {"A": 1.0, "B": 0.8, "C": 0.5}
}
```

Each `rule` is a named Python function in `services/scoring/rules.py`. The function
returns a score from 0 to 100 (or `unknown`), a short reason, and the ids of the
facts and claims it used.

## Deriving the profile (onboarding)

A VC's scoring profile is worked out from evidence, the same way the thesis is.

- Weights and rule parameters are set by **rules** over the confirmed deals and
  the partner's career history. The LLM never picks a number.
- Every weight and parameter stores an **explanation**: a short reason plus the
  `deal_ids` or `fact_ids` behind it.
- The partner sees the profile as sliders, each with its reason, and confirms it.

### Inputs

| Input | Source | Used for |
|---|---|---|
| The firm's deals at entry: stage, check size, lead share, headcount and age at the round date, sector concentration | `deal` + facts as of each round date ([onboarding spec](scout-onboarding-thesis.md)) | Base weights and the stage benchmarks inside rules |
| The recent trend: last 6 months vs the 12 before | Thesis trend points | A thesis-fit bonus for sectors and stages that are rising |
| The partner's career: operator vs investor background, function (engineering, product, sales, finance), past sectors, prior founding | Person Enrich dated history; titles mapped to function and seniority (Crustdata job title normalization where available) | Weight adjustments and optional criteria |
| The partner's own deals | `deal.championed_by_investor_id` | A partner-lens bonus within thesis fit |

### Rules (v1, deterministic)

All of these thresholds are data in `profile_rules.json`, not code. Adjusted weights
are re-normalised to sum to 1. Each rule fires only when its evidence meets the
minimum count shown.

| Evidence | Adjustment | Minimum evidence |
|---|---|---|
| ≥ 60% of deals pre-seed or seed | `team` +0.10, `traction` −0.10. The traction benchmark uses the median headcount at entry, not later-stage growth. | ≥ 5 deals |
| ≥ 60% of deals Series A or later | `traction` +0.10, `funding` +0.05, `team` −0.10, `market` −0.05 | ≥ 5 deals |
| The top sector has ≥ 70% of deals | `thesis_fit` +0.05 | ≥ 5 deals |
| The firm led ≥ 50% of its deals | `team` +0.05 (lead investors weigh founders more) | ≥ 5 deals |
| A sector or stage is rising in the trend | `thesis_fit` rule parameter `trend_bonus` for that sector or stage | ≥ 3 deals in the shift |
| The partner has ≥ 3 years in engineering or research roles | Adds the optional criterion `technical_depth` (0.10, taken evenly from the others) | Career facts |
| The partner was a founder | `team` rule parameter `founder_market_fit` turned on | Career facts |
| The partner has a finance or banking background | Adds the optional criterion `capital_efficiency` (funding raised vs headcount growth) | Career facts |
| The partner championed ≥ 2 deals in a sector | `thesis_fit` parameter `partner_lens` for that sector | ≥ 2 deals |
| Fewer than 5 deals in the window | **Generic weights**, labelled "low confidence: generic profile" | — |

### Calibration against peers (stretch)

This measures the firm's **revealed preferences**: how its deals looked at entry
compared with similar companies it didn't back.

1. Build a baseline: 20–30 companies in the same sectors and stages, with rounds in
   the same window, where the firm is not an investor (`company/search` +
   `company/enrich`, ≈ 60–100 credits).
2. Score both groups on every criterion, using facts as of each company's round date.
3. Criteria where the firm's deals score clearly above the baseline gain weight.
   Weight is proportional to the effect size (mean difference ÷ pooled standard
   deviation), capped at ±0.10 from the v1 weight.
4. The explanation then reads, for example: "Your deals had 2.1× the peers' headcount
   growth in the 6 months before the round → traction weight 0.30."

### Storage

- `scoring_profile` gains `origin` (`derived`/`edited`/`generic`), `confidence`, and
  `derivation`: a list of `{target, change, reason, evidence_ids}`.
- A partner edit creates a new version with `origin = edited`. Searches record which
  profile version they used.

## Criteria library

| Criterion | Evidence | Rule (summary) |
|---|---|---|
| Thesis fit | Company taxonomy, stage, geography, check size vs the confirmed thesis | Matches per thesis dimension; any exclusion caps the criterion at 0 |
| Team | Founders' dated career history (Person Enrich): relevant domain years, prior founding, technical depth | Points per signal. Pedigree (school, big-company background) only counts if `use_pedigree` is on, and it's off by default. |
| Traction | Headcount over time, hiring (Job Search), web traffic | Growth over the window against stage benchmarks |
| Funding | `funding.milestones`, grants (web-verified) | Stage and amount vs the thesis; a recent raise is a timing signal |
| Market | Competitors (Company Enrich), sector growth (company counts) | Crowding and growth signals |
| Momentum | News, launches, recent posts, events within the window | Count and recency of dated, positive events |
| Technical depth (optional) | Founders' engineering or research history, research profiles, technical hiring share (Job Search) | Points per signal; added by a profile rule |
| Capital efficiency (optional) | Total raised vs headcount and web traffic growth | The ratio against peers at the same stage; added by a profile rule |

The generic default weights (fallback) are the JSON example above.

**Completeness** = the share of criteria weight whose evidence is not `unknown`.

## Signals

These rules turn facts into signals. Every signal cites its facts and claims.

| Kind | Examples |
|---|---|
| `strong` | Headcount +50% in 6 months; a recent round led by a tier-1 investor; a founder with ≥ 5 years in the domain; a verified grant |
| `red_flag` | Headcount −20% in 6 months; a founder left; a deck claim contradicted; no web presence; the company description changed sector (a pivot) |
| `gap` | A criterion is `unknown`, or only self-reported. Each gap names the data that would settle it. |

## Suggested actions

These rules are evaluated in order, and the first match wins:

| Condition | Suggested action |
|---|---|
| Any thesis exclusion matched | `pass` (reason: the exclusion) |
| score ≥ `reach_out` and completeness ≥ `min_completeness` and no unresolved red flags | `reach_out` (ask for a call) |
| score ≥ `reach_out` but completeness < `min_completeness`, or a deck isn't available | `request_data` (moves to `in_dd`) |
| `watch` ≤ score < `reach_out` | `watch` |
| score < `watch` | `pass` |
| status `in_dd` and stage `ready_for_decision` and score ≥ `reach_out` | `invest` (generates a memo for the partner to review) |

The partner can always override. An override records who made it and why.

## Follow-up questions

- Generated from gaps, red flags and contradictions.
- Each question has a `motivated_by` link to the gap, fact or claim it addresses,
  and asks for specific evidence. For example: "Your deck says 40 engineers;
  public data shows 18 in October 2026. Can you share the current team list?"
- The LLM writes the wording. Questions without a `motivated_by` link are dropped.

## Investment memo

- **Sections:**
  - summary
  - thesis fit
  - team
  - traction
  - market and competition
  - funding history
  - strong signals
  - risks and red flags
  - open questions
  - recommendation
- Generated only from stored facts and claims, cited as `[f:id]` and `[c:id]`.
- **Post-check:** every number and date in the memo must appear in a cited fact or
  claim. Unsupported sentences are removed and listed as "removed: unsupported".
- Versioned. A re-score after new data marks the memo as stale.

## Re-scoring triggers

Re-scoring happens when any of these occurs:

- a new fact or claim arrives (DD ingestion, a watch event, a manual re-check)
- the scoring profile or thesis changes
- the partner overrides something

Each re-score writes a `score_snapshot` with the trigger. The UI shows what moved
the score, e.g. "+8 verified headcount, −4 grant unverifiable".

## Tests

- Rule unit tests on fixed facts:
  - unknown handling
  - self-reported weighting
  - contradiction penalty
  - an exclusion capping thesis fit
- Action rules: a table-driven test covering each row above.
- Memo post-check: a memo containing an unsupported number has that sentence removed.
- Determinism: the same facts and profile always give the same breakdown.
- Profile derivation, on fixed deal sets:
  - a seed-heavy firm gets a team-heavy profile
  - a Series A+ firm gets a traction-heavy profile
  - a partner with an engineering background gets `technical_depth` added
  - fewer than 5 deals gives the generic profile labelled low confidence
  - weights always sum to 1
  - every change has at least one evidence id
