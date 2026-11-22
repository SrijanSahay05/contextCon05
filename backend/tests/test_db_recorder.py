from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.mongo import mongo_db
from app.db.session import SessionLocal
from app.models.enums import Provider, SourceKind, UnitType
from app.models.evidence import Ledger, Source
from app.services.evidence.recorder import DbRecorder


def _record(recorder: DbRecorder, **overrides: object) -> object:
    args: dict[str, object] = dict(
        provider=Provider.crustdata, endpoint="/company/enrich", request={"domains": ["x.in"]},
        response=[{"matches": []}], units=2.0, unit_type=UnitType.credits, cached=False,
        run_id=None, kind=SourceKind.crustdata, request_hash="h1",
    )
    args.update(overrides)
    return recorder.record(**args)  # type: ignore[arg-type]


def test_record_then_lookup_returns_raw_response(db: Session) -> None:
    recorder = DbRecorder(SessionLocal, mongo_db)
    source_id = _record(recorder)

    hit = recorder.lookup("h1", timedelta(hours=1))
    assert hit is not None
    assert hit.source_id == source_id
    assert hit.response == [{"matches": []}]
    assert recorder.lookup("other", timedelta(hours=1)) is None


def test_cache_hit_adds_ledger_only_and_reuses_source(db: Session) -> None:
    recorder = DbRecorder(SessionLocal, mongo_db)
    first = _record(recorder)
    again = _record(recorder, units=0.0, cached=True)

    assert again == first
    assert len(db.scalars(select(Source)).all()) == 1
    ledger = db.scalars(select(Ledger).order_by(Ledger.id)).all()
    assert [(float(row.units), row.cached) for row in ledger] == [(2.0, False), (0.0, True)]


def test_llm_input_and_output_rows_share_one_source(db: Session) -> None:
    recorder = DbRecorder(SessionLocal, mongo_db)
    common = dict(provider=Provider.llm, endpoint="/v1/messages", kind=SourceKind.llm,
                  request_hash=None)
    first = _record(recorder, unit_type=UnitType.input_tokens, units=900.0, **common)
    second = _record(recorder, unit_type=UnitType.output_tokens, units=120.0, **common)

    assert first == second
    assert len(db.scalars(select(Source)).all()) == 1
    assert len(db.scalars(select(Ledger)).all()) == 2
