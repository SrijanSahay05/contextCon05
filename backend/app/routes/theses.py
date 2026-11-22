import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES
from app.models.entities import Company
from app.models.enums import ReliabilityTier, ReviewStatus, SourceKind
from app.models.evidence import Source
from app.models.onboarding import Deal
from app.repositories import theses
from app.schemas.thesis import AddedDeal, ThesisEdit, ThesisOut

router = APIRouter(
    prefix="/theses", tags=["theses"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)
Db = Annotated[Session, Depends(get_db)]


@router.get("/{thesis_id}", response_model=ThesisOut)
def get_thesis(thesis_id: UUID, investor_id: InvestorId, db: Db) -> ThesisOut:
    """The thesis with its points and the deals behind them."""
    return theses.to_out(db, theses.get_owned(db, thesis_id, investor_id))


@router.put("/{thesis_id}", response_model=ThesisOut)
def edit_thesis(thesis_id: UUID, body: ThesisEdit, investor_id: InvestorId, db: Db) -> ThesisOut:
    """Save the partner's edits. Every save creates a **new version with a new id**
    (status `draft`); use the returned `id` from then on."""
    old = theses.get_owned(db, thesis_id, investor_id)
    removed = set(body.removed_deal_ids)
    points = [
        p.model_dump(mode="json")
        | {"deal_ids": [str(i) for i in p.deal_ids if i not in removed]}
        for p in body.points
    ]
    added = [_add_deal(db, old.fund_id, deal) for deal in body.added_deals]
    if added:
        points.append({
            "dimension": "stage",
            "statement": "Deals added by the partner: "
                         + ", ".join(d.company_name for d in body.added_deals),
            "value": {d.round_type or "unknown": 1 for d in body.added_deals},
            "deal_ids": [str(i) for i in added],
        })
    fallback = old.created_at.date()
    new = theses.create(
        db, investor_id=investor_id, fund_id=old.fund_id,
        window=(old.window_start or fallback, old.window_end or fallback),
        confidence=old.confidence, points=points, summary=old.summary,
    )
    db.commit()
    return theses.to_out(db, new)


@router.post("/{thesis_id}/confirm", response_model=ThesisOut)
def confirm_thesis(thesis_id: UUID, investor_id: InvestorId, db: Db) -> ThesisOut:
    """Mark this version `confirmed`. New searches use the latest confirmed thesis."""
    thesis = theses.get_owned(db, thesis_id, investor_id)
    thesis.status = ReviewStatus.confirmed
    db.commit()
    return theses.to_out(db, thesis)


def _add_deal(db: Session, fund_id: uuid.UUID, added: AddedDeal) -> uuid.UUID:
    source = Source(kind=SourceKind.web, endpoint_or_url=added.url,
                    reliability_tier=ReliabilityTier.c)
    db.add(source)
    company = db.scalar(
        select(Company).where(func.lower(Company.name) == added.company_name.lower()).limit(1)
    )
    if company is None:
        # shortcut: a partner-added company has no Crustdata id yet, so it gets a negative
        # placeholder; make the column nullable once partner-added companies get enriched
        company = Company(crustdata_company_id=-(uuid.uuid4().int >> 66),
                          name=added.company_name)
        db.add(company)
    db.flush()
    deal = Deal(
        fund_id=fund_id, company_id=company.id, round_date=added.round_date,
        round_type=added.round_type, amount_usd=added.amount_usd, led=None,
        match_rule="partner_added", match_evidence={"url": added.url}, source_id=source.id,
    )
    db.add(deal)
    db.flush()
    return deal.id
