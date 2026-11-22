"""Thesis and deal persistence. A thesis's deals are the ones its points cite."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.entities import Company
from app.models.enums import Confidence, ReviewStatus
from app.models.onboarding import Deal, ScoringProfile, Thesis
from app.schemas.thesis import DealOut, ThesisOut, ThesisWindow


def next_version(db: Session, model: type[Thesis] | type[ScoringProfile],
                 investor_id: uuid.UUID) -> int:
    current = db.scalar(select(func.max(model.version)).where(model.investor_id == investor_id))
    return (current or 0) + 1


def get_owned(db: Session, thesis_id: uuid.UUID, investor_id: uuid.UUID) -> Thesis:
    thesis = db.get(Thesis, thesis_id)
    if thesis is None or thesis.investor_id != investor_id:
        raise ApiError(404, ErrorCode.not_found, "Thesis not found")
    return thesis


def create(
    db: Session, *, investor_id: uuid.UUID, fund_id: uuid.UUID, window: tuple[date, date],
    confidence: Confidence, points: list[dict[str, Any]], summary: str | None,
) -> Thesis:
    thesis = Thesis(
        investor_id=investor_id, fund_id=fund_id,
        version=next_version(db, Thesis, investor_id), status=ReviewStatus.draft,
        window_start=window[0], window_end=window[1], points=points, summary=summary,
        deal_count=len(cited_deal_ids(points)), confidence=confidence,
    )
    db.add(thesis)
    db.flush()
    return thesis


def cited_deal_ids(points: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for point in points:
        seen.update(dict.fromkeys(str(i) for i in point.get("deal_ids", [])))
    return list(seen)


def to_out(db: Session, thesis: Thesis) -> ThesisOut:
    ids = [uuid.UUID(i) for i in cited_deal_ids(thesis.points)]
    rows = db.execute(
        select(Deal, Company).join(Company, Company.id == Deal.company_id)
        .where(Deal.id.in_(ids), Deal.fund_id == thesis.fund_id)
        .order_by(Deal.round_date.desc().nulls_last())
    ).all() if ids else []
    deals = [
        DealOut(
            id=deal.id, company_id=company.id, company_name=company.name,
            company_domain=company.domain, round_date=deal.round_date,
            round_type=deal.round_type,
            amount_usd=float(deal.amount_usd) if deal.amount_usd is not None else None,
            led=deal.led, match_rule=deal.match_rule,
            championed_by_investor_id=deal.championed_by_investor_id, source_id=deal.source_id,
        )
        for deal, company in rows
    ]
    start = thesis.window_start or thesis.created_at.date()
    return ThesisOut(
        id=thesis.id, investor_id=thesis.investor_id, fund_id=thesis.fund_id,
        version=thesis.version, status=thesis.status,
        window=ThesisWindow(start=start, end=thesis.window_end or start),
        deal_count=thesis.deal_count, confidence=thesis.confidence,
        points=thesis.points, summary=thesis.summary, deals=deals,
        created_at=thesis.created_at,
    )
