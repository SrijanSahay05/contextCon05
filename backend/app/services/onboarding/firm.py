"""Firm name matching, steps 2-3: candidate investor records and the partner's confirmation.

The pure functions here turn Crustdata search/enrich responses into alias candidates
grouped by Crunchbase permalink; names are compared only via `names.normalize_name`.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.enums import RunKind
from app.models.runs import Job
from app.repositories import funds as fund_repo
from app.schemas.common import RunAccepted
from app.services.jobs import queue
from app.services.onboarding.names import normalize_name

MAX_ENRICH = 8
MAX_EXAMPLES = 3


def is_close(name: str, variants: list[str]) -> bool:
    """`name` equals a variant or contains it as whole words ("Accel-KKR" ~ "Accel")."""
    norm = normalize_name(name)
    return any(
        re.search(rf"(?<!\w){re.escape(v)}(?!\w)", norm)
        for v in (normalize_name(x) for x in variants) if v
    )


def search_companies(responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`company/search` results across variants, de-duplicated by Crustdata id, in order."""
    seen: set[int] = set()
    out = []
    for data in responses:
        for company in (data or {}).get("companies") or []:
            cid = company.get("crustdata_company_id")
            if cid is not None and cid not in seen:
                seen.add(cid)
                out.append(company)
    return out


def _investor_names(company: dict[str, Any]) -> list[str]:
    return list((company.get("funding") or {}).get("investors") or [])


def pick_for_enrich(
    companies: list[dict[str, Any]], variants: list[str], limit: int = MAX_ENRICH
) -> list[int]:
    """Companies to enrich: first one per distinct lookalike investor name, then fill up."""
    covered: set[str] = set()
    picked: list[int] = []
    for company in companies:
        close = {normalize_name(n) for n in _investor_names(company) if is_close(n, variants)}
        if close - covered:
            covered |= close
            picked.append(company["crustdata_company_id"])
    for company in companies:
        if company["crustdata_company_id"] not in picked:
            picked.append(company["crustdata_company_id"])
    return picked[:limit]


def group_candidates(
    enriched: list[tuple[dict[str, Any], str]],
    searched: list[dict[str, Any]],
    variants: list[str],
    official_name: str,
) -> list[dict[str, Any]]:
    """Group lookalike `investors_detailed` entries by permalink.

    `enriched` is (company_data, source_id of the enrich call). Each group carries up to
    3 example companies; `deal_count` counts searched companies listing that exact name.
    `preselected` only when exactly one group's name equals the official name.
    """
    groups: dict[str, dict[str, Any]] = {}
    for company, source_id in enriched:
        company_name = (company.get("basic_info") or {}).get("name")
        for inv in (company.get("funding") or {}).get("investors_detailed") or []:
            permalink, name = inv.get("permalink"), inv.get("name")
            if not permalink or not name or not is_close(name, variants):
                continue
            group = groups.setdefault(permalink, {
                "permalink": permalink, "canonical_name": name, "example_companies": [],
                "deal_count": 0, "preselected": False, "source_id": source_id,
            })
            if company_name and company_name not in group["example_companies"] \
                    and len(group["example_companies"]) < MAX_EXAMPLES:
                group["example_companies"].append(company_name)
    for group in groups.values():
        key = normalize_name(group["canonical_name"])
        listed = sum(
            1 for c in searched if key in {normalize_name(n) for n in _investor_names(c)}
        )
        group["deal_count"] = max(listed, len(group["example_companies"]))
    official = normalize_name(official_name)
    exact = [g for g in groups.values() if normalize_name(g["canonical_name"]) == official]
    if len(exact) == 1:
        exact[0]["preselected"] = True
    return sorted(groups.values(), key=lambda g: (not g["preselected"], -g["deal_count"]))


def confirm_aliases(
    db: Session, fund_id: uuid.UUID, investor_id: uuid.UUID, permalinks: list[str]
) -> RunAccepted:
    fund_repo.get_fund(db, fund_id)
    candidates = {c["permalink"]: c for c in fund_repo.alias_candidates(db, fund_id)}
    unknown = sorted(set(permalinks) - set(candidates))
    if unknown:
        raise ApiError(422, ErrorCode.validation_error, "Unknown permalinks for this fund",
                       {"permalinks": unknown})
    now = datetime.now(timezone.utc)
    for permalink in set(permalinks):
        c = candidates[permalink]
        fund_repo.upsert_alias(
            db, fund_id, permalink, c["canonical_name"], investor_id, now,
            uuid.UUID(c["source_id"]) if c.get("source_id") else None,
        )
    key = f"onboarding_thesis:{fund_id}:{','.join(sorted(set(permalinks)))}"
    subject = {"investor_id": str(investor_id), "fund_id": str(fund_id)}
    run_id = enqueue_run(db, subject, "onboarding_thesis", key)
    db.commit()
    return accepted(run_id)


def enqueue_run(
    db: Session, subject: dict[str, Any], kind: str, key: str,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    """A new run + job, or the run of the job already queued under `key`."""
    existing = db.scalar(select(Job).where(Job.idempotency_key == key))
    if existing is not None and existing.run_id is not None:
        return existing.run_id
    run = queue.create_run(db, RunKind.onboarding, subject)
    queue.enqueue(db, kind, payload or subject, key, run.id)
    return run.id


def accepted(run_id: uuid.UUID) -> RunAccepted:
    return RunAccepted(
        run_id=run_id, status_url=f"/runs/{run_id}", events_url=f"/runs/{run_id}/events"
    )
