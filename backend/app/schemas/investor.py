from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.schemas.common import (
    EX_FUND_ID,
    EX_INVESTOR_ID,
    EX_PROFILE_ID,
    EX_RUN_ID,
    EX_THESIS_ID,
    examples,
)

OnboardingStep = Literal[
    "confirm_identity", "confirm_aliases", "building_thesis", "review_thesis",
    "review_profile", "done",
]

EX_PERSON_CANDIDATE = {
    "crustdata_person_id": 90412233,
    "name": "Ananya Rao",
    "headline": "Partner at Kestrel Ventures | Fintech, B2B SaaS",
    "current_title": "Partner",
    "current_company": "Kestrel Ventures",
    "location": "Bengaluru, Karnataka, India",
    "linkedin_url": "https://www.linkedin.com/in/ananya-rao-example",
    "profile_picture_url": None,
}
EX_FUND_SUMMARY = {
    "id": EX_FUND_ID,
    "name": "Kestrel Ventures",
    "domain": "kestrel.vc",
    "crustdata_company_id": 7730154,
}


class OnboardRequest(BaseModel):
    """Send either `linkedin_url`, or both `name` and `firm`."""

    linkedin_url: str | None = None
    name: str | None = None
    firm: str | None = None

    model_config = examples(
        {"linkedin_url": "https://www.linkedin.com/in/ananya-rao-example"},
        {"name": "Ananya Rao", "firm": "Kestrel Ventures"},
    )

    @model_validator(mode="after")
    def _one_way_to_identify(self) -> Self:
        if not self.linkedin_url and not (self.name and self.firm):
            raise ValueError("send linkedin_url, or both name and firm")
        return self


class PersonCandidate(BaseModel):
    """A Crustdata person who might be the partner ("Is this you?")."""

    crustdata_person_id: int
    name: str
    headline: str | None
    current_title: str | None
    current_company: str | None
    location: str | None
    linkedin_url: str | None
    profile_picture_url: str | None

    model_config = examples(EX_PERSON_CANDIDATE)


class IdentityCandidates(BaseModel):
    """`investor_id` is new: send it as `X-Investor-Id` from now on. `candidates` may be
    empty (ask the partner to try a LinkedIn URL)."""

    investor_id: UUID
    candidates: list[PersonCandidate]

    model_config = examples({"investor_id": EX_INVESTOR_ID, "candidates": [EX_PERSON_CANDIDATE]})


class ConfirmIdentity(BaseModel):
    crustdata_person_id: int

    model_config = examples({"crustdata_person_id": 90412233})


class FundSummary(BaseModel):
    id: UUID
    name: str
    domain: str | None
    crustdata_company_id: int | None

    model_config = examples(EX_FUND_SUMMARY)


class InvestorOut(BaseModel):
    """The partner, their fund and where they are in onboarding. Use `onboarding_step` to
    pick the screen; `onboarding_run_id` is the run to follow while Scout is working."""

    id: UUID
    name: str | None
    title: str | None
    linkedin_url: str | None
    crustdata_person_id: int | None
    identity_confirmed_at: datetime | None
    fund: FundSummary | None
    onboarding_step: OnboardingStep
    onboarding_run_id: UUID | None
    current_thesis_id: UUID | None
    current_profile_id: UUID | None
    gmail_connected: bool
    created_at: datetime

    model_config = examples({
        "id": EX_INVESTOR_ID,
        "name": "Ananya Rao",
        "title": "Partner",
        "linkedin_url": "https://www.linkedin.com/in/ananya-rao-example",
        "crustdata_person_id": 90412233,
        "identity_confirmed_at": "2026-11-20T08:55:10Z",
        "fund": EX_FUND_SUMMARY,
        "onboarding_step": "review_thesis",
        "onboarding_run_id": EX_RUN_ID,
        "current_thesis_id": EX_THESIS_ID,
        "current_profile_id": EX_PROFILE_ID,
        "gmail_connected": False,
        "created_at": "2026-11-20T08:52:31Z",
    })
