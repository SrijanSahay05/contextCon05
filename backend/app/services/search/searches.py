"""Search lifecycle: parse a query into a draft, edit its filters, start its run."""

import uuid

from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.integrations.errors import LLMError
from app.models.enums import RunKind, SearchStatus
from app.models.onboarding import ScoringProfile, Thesis
from app.models.search import Search
from app.repositories import searches as repo
from app.schemas.common import RunAccepted
from app.schemas.search import FilterSpec, SearchCreate
from app.services.clients import clients_for_run
from app.services.jobs import queue
from app.services.onboarding.firm import accepted
from app.services.onboarding.identity import upstream_errors
from app.services.search.query_parser import parse_query

JOB_KIND = "search_run"


def create(db: Session, investor_id: uuid.UUID, body: SearchCreate) -> Search:
    thesis = repo.latest_confirmed(db, Thesis, investor_id)
    profile = repo.latest_confirmed(db, ScoringProfile, investor_id)
    with upstream_errors():
        try:
            spec, unresolved = parse_query(
                clients_for_run(None), body.query, thesis.points if thesis else None,
                body.as_of,
            )
        except LLMError as exc:
            raise ApiError(503, ErrorCode.upstream_unavailable, "The LLM is unavailable",
                           {"reason": str(exc)[:300]}) from exc
    search = Search(
        investor_id=investor_id, query_text=body.query,
        parsed_filters=spec.model_dump(mode="json"),
        unresolved=[u.model_dump(mode="json") for u in unresolved], as_of=body.as_of,
        thesis_id=thesis.id if thesis else None, profile_id=profile.id if profile else None,
        status=SearchStatus.draft,
    )
    db.add(search)
    db.commit()
    return search


def edit_filters(
    db: Session, search_id: uuid.UUID, investor_id: uuid.UUID, spec: FilterSpec
) -> Search:
    search = repo.get_owned(db, search_id, investor_id)
    if search.status != SearchStatus.draft:
        raise ApiError(409, ErrorCode.conflict, "Search is no longer a draft",
                       {"status": search.status})
    search.parsed_filters = spec.model_dump(mode="json")
    # the edited chips are the partner's answer to the unresolved terms
    search.unresolved = []
    db.commit()
    return search


def run(db: Session, search_id: uuid.UUID, investor_id: uuid.UUID) -> RunAccepted:
    search = repo.get_owned(db, search_id, investor_id)
    if search.run_id is not None:
        return accepted(search.run_id)
    if search.unresolved:
        raise ApiError(409, ErrorCode.conflict, "Resolve the unresolved terms first",
                       {"unresolved": search.unresolved})
    subject = {"search_id": str(search.id), "investor_id": str(investor_id)}
    run_ = queue.create_run(db, RunKind.search, subject)
    queue.enqueue(db, JOB_KIND, subject, f"{JOB_KIND}:{search.id}", run_.id)
    search.status, search.run_id = SearchStatus.running, run_.id
    db.commit()
    return accepted(run_.id)
