"""Investor lookups and the `InvestorOut` view (with the derived onboarding step)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.enums import ReviewStatus, RunKind
from app.models.identity import Fund, Investor
from app.models.onboarding import ScoringProfile, Thesis
from app.models.runs import Run
from app.repositories.funds import has_aliases
from app.schemas.investor import FundSummary, InvestorOut, OnboardingStep


def get_investor(db: Session, investor_id: uuid.UUID) -> Investor:
    investor = db.get(Investor, investor_id)
    if investor is None:
        raise ApiError(404, ErrorCode.not_found, "Investor not found")
    return investor


def _latest_onboarding_run(db: Session, investor_id: uuid.UUID) -> Run | None:
    return db.scalar(
        select(Run)
        .where(Run.kind == RunKind.onboarding)
        .where(Run.subject.contains({"investor_id": str(investor_id)}))
        .order_by(Run.created_at.desc())
        .limit(1)
    )


def _step(
    investor: Investor, aliased: bool, thesis: Thesis | None, profile: ScoringProfile | None
) -> OnboardingStep:
    if investor.identity_confirmed_at is None:
        return "confirm_identity"
    if not aliased:
        return "confirm_aliases"
    if thesis is None:
        return "building_thesis"
    if thesis.status != ReviewStatus.confirmed:
        return "review_thesis"
    if profile is None or profile.status != ReviewStatus.confirmed:
        return "review_profile"
    return "done"


def investor_out(db: Session, investor: Investor) -> InvestorOut:
    fund = db.get(Fund, investor.fund_id) if investor.fund_id else None
    thesis = db.scalar(
        select(Thesis).where(Thesis.investor_id == investor.id)
        .order_by(Thesis.version.desc()).limit(1)
    )
    profile = db.scalar(
        select(ScoringProfile).where(ScoringProfile.investor_id == investor.id)
        .order_by(ScoringProfile.version.desc()).limit(1)
    )
    run = _latest_onboarding_run(db, investor.id)
    aliased = fund is not None and has_aliases(db, fund.id)
    return InvestorOut(
        id=investor.id,
        name=investor.name or None,
        title=investor.title,
        linkedin_url=investor.linkedin_url,
        crustdata_person_id=investor.crustdata_person_id,
        identity_confirmed_at=investor.identity_confirmed_at,
        fund=FundSummary(id=fund.id, name=fund.name, domain=fund.domain,
                         crustdata_company_id=fund.crustdata_company_id) if fund else None,
        onboarding_step=_step(investor, aliased, thesis, profile),
        onboarding_run_id=run.id if run else None,
        current_thesis_id=thesis.id if thesis else None,
        current_profile_id=profile.id if profile else None,
        gmail_connected=False,  # shortcut: no gmail token model yet; wire up with phase 3
        created_at=investor.created_at,
    )
