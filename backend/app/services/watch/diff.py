"""Compare two company fact snapshots and suggest what to do about the change. Pure.

A snapshot maps predicate → list of fact values (see `recheck_job.snapshot`). A predicate
is compared only when both snapshots have it, so a field the re-check did not fetch
(news, founders) is never reported as removed, and its first sighting is a baseline.
"""

import json
from typing import Any

from app.models.enums import SuggestedAction
from app.services.evidence.facts_mapper import (
    DESCRIPTION,
    FOUNDER,
    FUNDING_ROUND,
    HEADCOUNT_TOTAL,
    INDUSTRIES,
    NEWS_ITEM,
)

HEADCOUNT_CHANGE = 0.10  # relative move that counts as a change
LARGE_RAISE_USD = 5_000_000
# shortcut: the default profile's reach_out threshold, not the investor's own profile;
# read the search's profile thresholds if investors start tuning them
REACH_OUT_SCORE = 65.0

HEADCOUNT = "headcount_change"
NEW_ROUND = "new_funding_round"
NEWS = "news"
PIVOT = "possible_pivot"
FOUNDER_LEFT = "founder_left"

Snapshot = dict[str, list[Any]]


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _new(before: list[Any], after: list[Any]) -> list[Any]:
    seen = {_key(v) for v in before}
    return [v for v in after if _key(v) not in seen]


def _change(field: str, before: Any, after: Any, kind: str, summary: str) -> dict[str, Any]:
    return {"field": field, "before": before, "after": after, "summary": summary, "kind": kind}


def diff(before: Snapshot, after: Snapshot) -> list[dict[str, Any]]:
    """`changes` items `{field, before, after, summary, kind}`; empty when nothing moved."""
    both = {p for p in before if before[p] and after.get(p)}
    out: list[dict[str, Any]] = []

    if HEADCOUNT_TOTAL in both:
        old, new = before[HEADCOUNT_TOTAL][-1], after[HEADCOUNT_TOTAL][-1]
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and old > 0:
            ratio = (new - old) / old
            if abs(ratio) >= HEADCOUNT_CHANGE:
                out.append(_change(HEADCOUNT_TOTAL, old, new, HEADCOUNT,
                                   f"Headcount {ratio:+.0%} ({old} → {new})"))

    if FUNDING_ROUND in both:
        for r in _new(before[FUNDING_ROUND], after[FUNDING_ROUND]):
            amount = r.get("amount_usd") if isinstance(r, dict) else None
            label = (r.get("round_type") if isinstance(r, dict) else None) or "round"
            money = f" of ${amount:,.0f}" if isinstance(amount, (int, float)) else ""
            out.append(_change(FUNDING_ROUND, None, r, NEW_ROUND, f"New {label}{money}"))

    if NEWS_ITEM in both:
        for n in _new(before[NEWS_ITEM], after[NEWS_ITEM]):
            title = n.get("title") if isinstance(n, dict) else None
            out.append(_change(NEWS_ITEM, None, n, NEWS, f"In the news: {title or 'new item'}"))

    if INDUSTRIES in both:
        old_i, new_i = before[INDUSTRIES][-1], after[INDUSTRIES][-1]
        if sorted(map(str, old_i or [])) != sorted(map(str, new_i or [])):
            out.append(_change(INDUSTRIES, old_i, new_i, PIVOT, "Industries changed"))
    if DESCRIPTION in both and before[DESCRIPTION][-1] != after[DESCRIPTION][-1]:
        out.append(_change(DESCRIPTION, before[DESCRIPTION][-1], after[DESCRIPTION][-1], PIVOT,
                           "Description changed"))

    if FOUNDER in both:
        names = {f.get("name") for f in after[FOUNDER] if isinstance(f, dict)}
        for f in before[FOUNDER]:
            if isinstance(f, dict) and f.get("name") not in names:
                out.append(_change(FOUNDER, f, None, FOUNDER_LEFT,
                                   f"Founder left: {f.get('name')}"))
    return out


def _large_raise(c: dict[str, Any]) -> bool:
    amount = (c["after"] or {}).get("amount_usd")
    return isinstance(amount, (int, float)) and amount >= LARGE_RAISE_USD


def suggest(changes: list[dict[str, Any]], score: float | None) -> SuggestedAction | None:
    """Bad news (decline, founder left) → `watch`/`pass`; a pivot, large raise or growth →
    `reach_out`/`request_data`; split on the re-scored `score` vs `REACH_OUT_SCORE`."""
    high = score is not None and score >= REACH_OUT_SCORE
    if any(c["kind"] == FOUNDER_LEFT or (c["kind"] == HEADCOUNT and c["after"] < c["before"])
           for c in changes):
        return SuggestedAction.watch if high else SuggestedAction.pass_
    if any(c["kind"] == PIVOT or (c["kind"] == NEW_ROUND and _large_raise(c))
           or (c["kind"] == HEADCOUNT and c["after"] > c["before"]) for c in changes):
        return SuggestedAction.reach_out if high else SuggestedAction.request_data
    return None
