# Scout run parameters

Intended behaviour of the inputs to a Scout run. The code is in `backend/app/scout_params/`.

## Entry paths

- **Profile path.** The investor gives only `name`, `firm`, `linkedin_url` and `consent`. The system resolves them (Person Enrich + Company Identify), then profiles the investor's posts and their firm's portfolio. From that it infers the thesis and the ranking weights.
- **Thesis path.** A plain-English `thesis_text` and/or a filled `thesis`. Client requests and hidden tests come in this way.

Every inferred value stays editable by the investor. `field_origins` and `Weight.origin` record who set each value: `lens_default`, `inferred` or `investor`.

## Parameter groups (`ScoutRequest`)

| Group | Model | Purpose |
|---|---|---|
| 0 | `InvestorIdentity`, `ResolvedIdentity`, `InvestorProfile` | Who is asking; what was resolved and inferred about them |
| A | `Thesis` | Hard gates: sector, business model, geography, founded window, stage, headcount, relationship, exclusions |
| B | `SignalThresholds` | Soft gates: 6-month growth (with a size floor), months since last round, minimum data coverage |
| C | `Ranking` | Lens preset, 21 signal weights summing to 100, inference caps, kill rules |
| D | `FounderPreferences` | Technical co-founder, repeat founder, domain years, prior-employer hypergrowth, co-founder overlap |
| — | `DecisionThresholds` | Meet ≥ 75 score and ≥ 0.7 confidence; Watch ≥ 50 |
| E | `RunControls` | Credit and profiling budgets, time limit, `as_of` (replay), top N, staleness, never pad |

Defaults live in `backend/app/scout_params/defaults.json`, so a requirement change is a one-line edit there.

## Weights

- Signals, their categories, Crustdata source fields and shares are defined in `signals.py`.
- Lens presets (`lenses.py`) set category weights. Each category's weight is split across its signals by share.
- `infer_weights` computes `normalize(w_lens + α·Δportfolio + β·Δposts)`:
  - Each move is capped at `max_delta` from the lens base.
  - Each inferred weight is capped at `max_weight`.
  - The LLM only produces tagged `SignalNudge`s; it never sets a weight.
- The weights panel uses:
  - `set_weight`: a slider move. Other unlocked weights rebalance to keep the total at 100.
  - `set_locked` and `reset_weights`.
  - `panel_order`, which returns the top N weights.
- Re-ranking reads cached facts, so moving a slider costs no credits.

## Protected inputs

Keys in `PROTECTED_INPUTS` (college, age, gender, caste, religion, surname and similar) are rejected anywhere in a request. They are never used as signals or as inputs to weight inference. These are proxies for protected traits, and excluding them is deliberate.

## Schema for the frontend

```sh
cd backend && uv run python -m app.scout_params.export_schema > scout_request.schema.json
```

Example request: `backend/tests/fixtures/scout_request.example.json`.
