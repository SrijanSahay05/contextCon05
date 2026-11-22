"""One place that builds the external clients for a run, wired to the DB recorder.

Tests swap in fakes by passing `transport` / `llm_client`; production passes nothing.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.db.mongo import mongo_db
from app.db.session import SessionLocal
from app.integrations.crustdata import CrustdataClient
from app.integrations.llm import LLMClient
from app.integrations.web import WebClient
from app.services.evidence.recorder import DbRecorder


@dataclass
class Clients:
    crustdata: CrustdataClient
    web: WebClient
    llm: LLMClient


def clients_for_run(
    run_id: uuid.UUID | None,
    *,
    transport: httpx.BaseTransport | None = None,
    llm_client: Any = None,
) -> Clients:
    settings = get_settings()
    recorder = DbRecorder(SessionLocal, mongo_db)
    return Clients(
        crustdata=CrustdataClient(settings, recorder, transport, run_id),
        web=WebClient(settings, recorder, transport, run_id),
        llm=LLMClient(settings, recorder, llm_client, run_id),
    )
