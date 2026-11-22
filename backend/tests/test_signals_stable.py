from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Company
from app.models.enums import SignalKind
from app.models.identity import Investor
from app.models.search import Candidate, Search, Signal
from app.repositories.scores import replace_signals
from app.services.scoring.signals import SignalDraft


def test_rescore_keeps_ids_of_signals_that_still_hold(db: Session) -> None:
    investor = Investor(name="P")
    company = Company(crustdata_company_id=42, name="Acme")
    db.add_all([investor, company])
    db.flush()
    search = Search(investor_id=investor.id, query_text="q", parsed_filters={}, unresolved=[])
    db.add(search)
    db.flush()
    candidate = Candidate(search_id=search.id, company_id=company.id, breakdown=[])
    db.add(candidate)
    db.flush()

    gap = SignalDraft(SignalKind.gap, "market unknown: Needs a competitor list.")
    flag = SignalDraft(SignalKind.red_flag, "Headcount fell 30%")
    replace_signals(db, candidate.id, [gap, flag])
    db.commit()
    before = {s.text: s.id for s in db.scalars(select(Signal))}

    replace_signals(db, candidate.id, [gap])  # the red flag no longer holds
    db.commit()
    after = {s.text: s.id for s in db.scalars(select(Signal))}
    assert after == {gap.text: before[gap.text]}  # same id, so questions keep their link
