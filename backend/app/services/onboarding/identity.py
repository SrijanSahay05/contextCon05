"""Identifying the partner: LinkedIn or name + firm → "Is this you?" candidates → confirm.

Candidates are stored as `identity_candidate` facts on the investor (each citing the
Crustdata call that returned it), so confirmation can only pick one of them.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.integrations.errors import (
    CreditsExhausted,
    CrustdataAuthError,
    CrustdataBadRequest,
    SourceUnavailable,
)
from app.models.enums import ExtractedBy, SubjectType
from app.models.evidence import Fact
from app.models.identity import Investor
from app.repositories import funds as fund_repo
from app.repositories.investors import get_investor
from app.schemas.common import RunAccepted
from app.schemas.investor import IdentityCandidates, OnboardRequest, PersonCandidate
from app.services.clients import clients_for_run
from app.services.onboarding.firm import accepted, enqueue_run

CANDIDATE = "identity_candidate"
RECENT_MOVE = timedelta(days=90)
MAX_PEOPLE = 10
MAX_FIRMS = 5


@contextmanager
def upstream_errors() -> Iterator[None]:
    """Crustdata failures → the API error envelope."""
    try:
        yield
    except CreditsExhausted as exc:
        raise ApiError(402, ErrorCode.credits_exhausted, "Crustdata is out of credits") from exc
    except (SourceUnavailable, CrustdataAuthError, CrustdataBadRequest) as exc:
        raise ApiError(503, ErrorCode.upstream_unavailable, "Crustdata is unavailable",
                       {"reason": str(exc)[:300]}) from exc


def _current_job(person: dict[str, Any], prefer: set[int]) -> dict[str, Any]:
    current = ((person.get("experience") or {}).get("employment_details") or {}).get("current")
    jobs = list(current or [])
    preferred = [j for j in jobs if j.get("crustdata_company_id") in prefer]
    job: dict[str, Any] = (preferred or jobs or [{}])[0]
    return job


def parse_person(person: dict[str, Any], prefer: set[int] | None = None) -> dict[str, Any]:
    """A Crustdata person (enrich `person_data` or a search profile) → candidate + employer."""
    basic = person.get("basic_profile") or {}
    job = _current_job(person, prefer or set())
    location = basic.get("location")
    picture = basic.get("profile_picture_permalink") or (
        person.get("professional_network") or {}).get("profile_picture_permalink")
    handles = (person.get("social_handles") or {}).get("professional_network_identifier") or {}
    candidate = PersonCandidate(
        crustdata_person_id=person["crustdata_person_id"],
        name=basic.get("name") or "",
        headline=basic.get("headline"),
        current_title=basic.get("current_title") or job.get("title"),
        current_company=job.get("name"),
        location=location.get("raw") if isinstance(location, dict) else location,
        linkedin_url=handles.get("profile_url"),
        profile_picture_url=picture,
    )
    domain = job.get("company_website_domain") or job.get("company_website")
    employer = {
        "crustdata_company_id": job.get("crustdata_company_id"),
        "name": job.get("name"),
        "domain": domain,
        "title": job.get("title"),
        "start_date": job.get("start_date"),
    }
    return {"candidate": candidate.model_dump(), "employer": employer}


def _by_linkedin(linkedin_url: str) -> list[tuple[dict[str, Any], uuid.UUID, str]]:
    crust = clients_for_run(None).crustdata
    try:
        result = crust.person_enrich({"professional_network_profile_urls": [linkedin_url]})
    except CrustdataBadRequest:
        return []  # the URL doesn't resolve to a person: the partner tries name + firm
    out = []
    for i, item in enumerate(result.data or []):
        for j, match in enumerate(item.get("matches") or []):
            if match.get("person_data"):
                out.append((parse_person(match["person_data"]), result.source_id,
                            f"[{i}].matches[{j}].person_data"))
    return out


def _by_name(name: str, firm: str) -> list[tuple[dict[str, Any], uuid.UUID, str]]:
    crust = clients_for_run(None).crustdata
    firms = crust.company_identify({"names": [firm]})
    ids = [
        m["company_data"]["crustdata_company_id"]
        for item in firms.data or [] for m in item.get("matches") or []
        if (m.get("company_data") or {}).get("crustdata_company_id") is not None
    ][:MAX_FIRMS]
    if not ids:
        return []
    people = crust.person_search({
        "filters": {"op": "and", "conditions": [
            {"field": "basic_profile.name", "type": "(.)", "value": name},
            {"field": "experience.employment_details.current.company_id", "type": "in",
             "value": ids},
        ]},
        "limit": MAX_PEOPLE,
    })
    return [
        (parse_person(p, set(ids)), people.source_id, f"profiles[{i}]")
        for i, p in enumerate((people.data or {}).get("profiles") or [])
    ]


def onboard(db: Session, body: OnboardRequest) -> IdentityCandidates:
    with upstream_errors():
        if body.linkedin_url:
            found = _by_linkedin(body.linkedin_url)
        else:
            assert body.name and body.firm  # the schema validator guarantees one way
            found = _by_name(body.name, body.firm)
    name = body.name or (found[0][0]["candidate"]["name"] if len(found) == 1 else "")
    investor = Investor(name=name)
    db.add(investor)
    db.flush()
    for value, source_id, path in found:
        db.add(Fact(
            subject_type=SubjectType.investor, subject_id=investor.id, predicate=CANDIDATE,
            value=value, as_of=date.today(), source_id=source_id, locator={"path": path},
            extracted_by=ExtractedBy.rule,
        ))
    db.commit()
    return IdentityCandidates(
        investor_id=investor.id,
        candidates=[PersonCandidate(**v["candidate"]) for v, _, _ in found],
    )


def _started(start_date: str | None) -> date | None:
    if not start_date:
        return None
    try:
        return datetime.fromisoformat(start_date).date()
    except ValueError:
        return None


def confirm_identity(db: Session, investor_id: uuid.UUID, person_id: int) -> RunAccepted:
    investor = get_investor(db, investor_id)
    if investor.crustdata_person_id not in (None, person_id):
        raise ApiError(409, ErrorCode.conflict, "Identity already confirmed as another person")
    facts = db.scalars(
        select(Fact).where(Fact.subject_type == SubjectType.investor,
                           Fact.subject_id == investor_id, Fact.predicate == CANDIDATE)
    )
    chosen = next(
        (f.value for f in facts if f.value["candidate"]["crustdata_person_id"] == person_id),
        None,
    )
    if chosen is None:
        raise ApiError(422, ErrorCode.validation_error,
                       "crustdata_person_id is not one of the candidates",
                       {"crustdata_person_id": person_id})
    candidate, employer = chosen["candidate"], chosen["employer"]
    if not employer.get("name"):
        raise ApiError(409, ErrorCode.conflict, "This person has no current employer on record")
    url = candidate.get("linkedin_url")
    if url and db.scalar(select(Investor.id).where(
            Investor.linkedin_url == url, Investor.id != investor_id)):
        raise ApiError(409, ErrorCode.conflict, "Another investor already confirmed this person")

    fund = fund_repo.fund_for_company(
        db, employer.get("crustdata_company_id"), employer["name"], employer.get("domain"))
    investor.crustdata_person_id = person_id
    investor.name = candidate["name"] or investor.name
    investor.title = candidate.get("current_title")
    investor.linkedin_url = url or investor.linkedin_url
    investor.fund_id = fund.id
    investor.identity_confirmed_at = investor.identity_confirmed_at or datetime.now(timezone.utc)

    started = _started(employer.get("start_date"))
    subject = {"investor_id": str(investor_id), "fund_id": str(fund.id)}
    payload = {
        **subject,
        "employer": employer,
        # PRD edge case: a move < 3 months ago means past deals only feed the partner lens
        "recent_move": bool(started and date.today() - started < RECENT_MOVE),
    }
    run_id = enqueue_run(db, subject, "onboarding_identity",
                         f"onboarding_identity:{investor_id}", payload)
    db.commit()
    return accepted(run_id)
