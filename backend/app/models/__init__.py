"""SQLAlchemy ORM models. Import new models here so Alembic autogenerate sees them."""

from app.models.actions import Memo, Outreach, Watch, WatchEvent
from app.models.base import Base
from app.models.dd import (
    Claim,
    DDItem,
    DDRequest,
    Document,
    MailAccount,
    MailMessage,
    MailThread,
    Verification,
)
from app.models.entities import Company, CompanyPerson, Person
from app.models.evidence import Fact, Ledger, Source
from app.models.identity import Fund, FundAlias, Investor, InvestorPostLink
from app.models.onboarding import Deal, ScoringProfile, Thesis
from app.models.runs import Job, Run, RunStep
from app.models.search import Candidate, Question, ScoreSnapshot, Search, Signal

__all__ = [
    "Base",
    "Candidate",
    "Claim",
    "Company",
    "CompanyPerson",
    "DDItem",
    "DDRequest",
    "Deal",
    "Document",
    "Fact",
    "Fund",
    "FundAlias",
    "Investor",
    "InvestorPostLink",
    "Job",
    "Ledger",
    "MailAccount",
    "MailMessage",
    "MailThread",
    "Memo",
    "Outreach",
    "Person",
    "Question",
    "Run",
    "RunStep",
    "ScoreSnapshot",
    "ScoringProfile",
    "Search",
    "Signal",
    "Source",
    "Thesis",
    "Verification",
    "Watch",
    "WatchEvent",
]
