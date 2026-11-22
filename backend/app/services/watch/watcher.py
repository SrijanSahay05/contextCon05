"""Crustdata company entity watches and their webhook deliveries.

One Crustdata watch per (company, reason) is shared by every candidate row for that
company, so a second investor watching the same company costs no extra watch.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.mongo import mongo_db
from app.db.session import SessionLocal
from app.models.actions import Watch, WatchEvent
from app.models.entities import Company
from app.models.enums import Provider, SourceKind, UnitType, WatchReason
from app.models.search import Candidate
from app.repositories import watch as repo
from app.schemas.watch import WatchEventOut
from app.services.clients import Clients
from app.services.evidence.recorder import DbRecorder

WEBHOOK_PATH = "/webhooks/crustdata/watch"
REFRESH_HOURS = 30 * 24  # company entity watches refresh at Crustdata's 30-day baseline
TRACK = {"op": "or", "conditions": [
    {"field": "headcount.total", "type": "changed"},
    {"field": "funding.last_fundraise_date", "type": "changed"},
    {"field": "news", "type": "added"},
]}
FIELDS = ["basic_info", "headcount", "funding", "news"]


def webhook_url(public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}{WEBHOOK_PATH}?token={get_settings().webhook_secret}"


def watch_request(crustdata_company_id: int, public_base_url: str) -> dict[str, Any]:
    return {
        "entities": {"crustdata_company_ids": [crustdata_company_id]},
        "track": TRACK,
        "fields": FIELDS,
        "config": {"trigger": {"type": "interval", "every_hours": REFRESH_HOURS}},
        "notifications": [{"type": "webhook", "url": webhook_url(public_base_url)}],
    }


def ensure_watch(
    db: Session, clients: Clients, candidate: Candidate, reason: WatchReason,
    public_base_url: str,
) -> Watch:
    """Call when a candidate moves to `watch` or `pass`. Idempotent per (company, reason):
    the Crustdata watch is created once and reused. Flushes; the caller commits."""
    mine = repo.find_watch(db, candidate.company_id, reason, candidate.id)
    if mine is not None:
        return mine
    shared = repo.find_watch(db, candidate.company_id, reason)
    crust_id = shared.crustdata_watch_id if shared else None
    if crust_id is None:
        company = db.get_one(Company, candidate.company_id)
        result = clients.crustdata.watch_company_create(
            watch_request(company.crustdata_company_id, public_base_url))
        crust_id = int(result.data["id"])
    row = Watch(company_id=candidate.company_id, candidate_id=candidate.id,
                crustdata_watch_id=crust_id, reason=reason)
    db.add(row)
    db.flush()
    return row


def send_test_notification(clients: Clients, watch: Watch) -> Any:
    """Ask Crustdata to push one sample delivery through the watch (free, for the demo)."""
    assert watch.crustdata_watch_id is not None
    return clients.crustdata.watch_test_notification(watch.crustdata_watch_id, {}).data


def record_delivery(payload: dict[str, Any]) -> uuid.UUID:
    """Store the webhook body as a `crustdata` source (raw payload in Mongo)."""
    return DbRecorder(SessionLocal, mongo_db).record(
        provider=Provider.crustdata, endpoint=WEBHOOK_PATH, request={}, response=payload,
        units=0, unit_type=UnitType.credits, cached=False, run_id=None,
        kind=SourceKind.crustdata)


def watches_for_delivery(db: Session, payload: dict[str, Any]) -> list[Watch]:
    """Watches a delivery is about: `metadata.watch_id` (real runs and test notifications
    share the envelope) or each `results[].record.crustdata_company_id`."""
    meta = payload.get("metadata") or {}
    watch_id = meta.get("watch_id", payload.get("watch_id"))
    company_ids = [r["record"]["crustdata_company_id"] for r in payload.get("results") or []
                   if isinstance(r, dict) and isinstance(r.get("record"), dict)
                   and isinstance(r["record"].get("crustdata_company_id"), int)]
    try:
        crust_watch = int(watch_id) if watch_id is not None else None
    except (TypeError, ValueError):
        crust_watch = None
    return [w for w in repo.watches_matching(db, crust_watch, company_ids)
            if w.candidate_id is not None]


def event_out(event: WatchEvent, watch: Watch, company: Company) -> WatchEventOut:
    assert watch.candidate_id is not None  # listed events always join a candidate
    changes = [{k: c.get(k) for k in ("field", "before", "after", "summary")}
               for c in event.changes]
    reason = "; ".join(c["summary"] for c in changes if c["summary"]) or None
    return WatchEventOut.model_validate({
        "id": event.id, "watch_id": watch.id, "candidate_id": watch.candidate_id,
        "company_id": company.id, "company_name": company.name, "reason": watch.reason,
        "changes": changes, "suggested_action": event.suggested_action,
        "suggested_reason": reason if event.suggested_action else None,
        "status": event.status, "source_id": event.source_id, "created_at": event.created_at,
    })
