"""Score a candidate from stored facts and claims, and record what changed.

No API or LLM calls, so re-scoring is free. Flushes; the caller commits.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.actions import Memo
from app.models.entities import Company
from app.models.enums import SignalKind, SnapshotTrigger
from app.models.search import Candidate, ScoreSnapshot, Search
from app.repositories import scores
from app.services.scoring.actions import suggest
from app.services.scoring.engine import Profile, score
from app.services.scoring.rules import GRANT, UNKNOWN, Evidence
from app.services.scoring.signals import signals_for


def _profile(db: Session, search: Search) -> Profile:
    row = scores.profile_for(db, search)
    if row is None:
        return Profile.generic()
    return Profile(row.criteria, row.thresholds, float(row.self_reported_weight),
                   row.source_tiers, row.version)


def _delta(before: list[Any], after: list[Any]) -> list[dict[str, Any]]:
    """Per-criterion change since the previous snapshot, e.g. `+8 traction: <reason>`."""
    old = {c["key"]: c for c in before}
    out = []
    for c in after:
        prev = old.get(c["key"], {}).get("score", UNKNOWN)
        now = c["score"]
        if prev == now:
            continue
        if UNKNOWN in (prev, now):
            label = f"{c['key']} {'now known' if prev == UNKNOWN else 'now unknown'}"
            change: float | str = "known" if prev == UNKNOWN else "unknown"
        else:
            change = round(float(now) - float(prev), 1)
            label = f"{change:+g} {c['key']}"
        out.append({"key": c["key"], "before": prev, "after": now, "change": change,
                    "reason": f"{label}: {c['reason']}"})
    return out


def score_candidate(
    db: Session, candidate_id: uuid.UUID, trigger: SnapshotTrigger = SnapshotTrigger.initial
) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise ApiError(404, ErrorCode.not_found, "Candidate not found")
    search = db.get(Search, candidate.search_id)
    company = db.get(Company, candidate.company_id)
    assert search is not None and company is not None  # non-null FKs
    profile = _profile(db, search)
    thesis = scores.thesis_for(db, search)
    people = [p.id for p, _ in scores.founders(db, company.id)]
    evidence = Evidence(
        items=scores.fact_items(db, company.id, people) + scores.claim_items(db, candidate.id),
        as_of=search.as_of or date.today(),
        thesis_points=list(thesis.points) if thesis else [],
        company_name=company.name,
    )

    breakdown = score(evidence, profile)
    drafts = signals_for(evidence, breakdown)
    scores.replace_signals(db, candidate.id, drafts)
    action, reason = suggest(
        score=breakdown.score, completeness=breakdown.completeness,
        exclusion=breakdown.exclusion, thresholds=profile.thresholds,
        red_flags=sum(d.kind == SignalKind.red_flag for d in drafts),
        has_deck=scores.has_deck(db, candidate.id),
        status=candidate.status, dd_stage=candidate.dd_stage,
        unmet=unmet_requirements(search, evidence),
    )

    rows = breakdown.to_json()
    history = scores.snapshots(db, candidate.id)
    delta = _delta(history[-1].breakdown, rows) if history else []
    candidate.score = breakdown.score
    candidate.completeness = breakdown.completeness
    candidate.breakdown = rows
    candidate.profile_version = profile.version
    candidate.suggested_action = action
    candidate.suggested_reason = reason
    candidate.updated_at = func.clock_timestamp()
    db.add(ScoreSnapshot(
        candidate_id=candidate.id, score=breakdown.score, completeness=breakdown.completeness,
        breakdown=rows, profile_version=profile.version, trigger=trigger, delta=delta,
        reason=("; ".join(d["reason"] for d in delta)[:500] or None),
        # clock_timestamp, not now(): several snapshots in one transaction stay ordered
        created_at=func.clock_timestamp(),
    ))
    # a memo describes the score it was written from; any rescore makes it stale
    db.execute(update(Memo).where(Memo.candidate_id == candidate.id).values(stale=True))
    db.flush()
    db.refresh(candidate)
    return candidate


def unmet_requirements(search: Search, evidence: Evidence) -> tuple[str, ...]:
    """What the search required that no stored fact verifies (grants: a quoted `grant`)."""
    grants = (search.parsed_filters or {}).get("grants") or {}
    if grants.get("required") and not evidence.get(GRANT):
        return ("a government grant",)
    return ()


def score_search(db: Session, search_id: uuid.UUID,
                 trigger: SnapshotTrigger = SnapshotTrigger.initial) -> list[Candidate]:
    ids = db.scalars(select(Candidate.id).where(Candidate.search_id == search_id)
                     .order_by(Candidate.id)).all()
    return [score_candidate(db, i, trigger) for i in ids]
