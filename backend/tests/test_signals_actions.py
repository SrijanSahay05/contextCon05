from datetime import date
from typing import Any

import pytest

from app.models.enums import (
    CandidateStatus,
    DDStage,
    SignalKind,
    SuggestedAction,
    VerificationResult,
)
from app.services.scoring.actions import suggest
from app.services.scoring.engine import Profile, score
from app.services.scoring.rules import Evidence, Item
from app.services.scoring.signals import signals_for

AS_OF = date(2026, 11, 1)
P = "22222222-2222-2222-2222-222222222222"
THRESH = {"reach_out": 65, "watch": 45, "min_completeness": 0.5}


def sigs(*items: Item) -> list[Any]:
    ev = Evidence(list(items), AS_OF, company_name="Acme")
    return signals_for(ev, score(ev, Profile.generic()))


def kinds(signals: list[Any], kind: SignalKind) -> list[str]:
    return [s.text for s in signals if s.kind == kind]


DOMAIN = Item(99, "domain", "acme.in", None, tier="A")


@pytest.mark.parametrize(("items", "kind", "text", "cites"), [
    ([Item(1, "headcount_at", 10, date(2026, 3, 1), tier="A"),
      Item(2, "headcount_at", 16, date(2026, 10, 1), tier="A")],
     SignalKind.strong, "Headcount 10 → 16", (1, 2)),
    ([Item(1, "headcount_at", 50, date(2026, 3, 1), tier="A"),
      Item(2, "headcount_at", 35, date(2026, 10, 1), tier="A")],
     SignalKind.red_flag, "Headcount fell", (1, 2)),
    ([Item(3, "funding_round", {"round_type": "seed", "lead_investors": ["Accel"]},
           date(2026, 9, 1), tier="A")],
     SignalKind.strong, "Recent seed", (3,)),
    ([Item(4, "employment", {"title": "PM", "company_name": "X", "start": "2018-01-01"},
           date(2018, 1, 1), P, tier="A")],
     SignalKind.strong, "years of experience", (4,)),
    ([Item(5, "employment", {"title": "CEO", "company_name": "Acme", "start": "2024-01-01",
                             "end": "2026-08-01"}, date(2024, 1, 1), P, tier="A")],
     SignalKind.red_flag, "left Acme", (5,)),
    ([Item(6, "grant", {"program": "BIRAC BIG"}, date(2026, 5, 1), tier="A")],
     SignalKind.strong, "Verified grant: BIRAC BIG", (6,)),
    ([Item(7, "industries", ["Fintech"], date(2025, 1, 1), tier="A"),
      Item(8, "industries", ["Gaming"], date(2026, 6, 1), tier="A")],
     SignalKind.red_flag, "possible pivot", (7, 8)),
])
def test_signal_rules(items: list[Item], kind: SignalKind, text: str,
                      cites: tuple[int, ...]) -> None:
    out = [s for s in sigs(DOMAIN, *items) if s.kind == kind and text in s.text]
    assert out and out[0].fact_ids == cites


def test_contradicted_claim_is_red_flag_citing_claim() -> None:
    claim = Item("c9", "headcount", 60, date(2026, 10, 1),
                 verification=VerificationResult.contradicted)
    out = sigs(DOMAIN, Item(1, "headcount_at", 40, date(2026, 3, 1), tier="A"),
               Item(2, "headcount_at", 42, date(2026, 10, 1), tier="A"), claim)
    flags = [s for s in out if s.kind == SignalKind.red_flag and "contradicted" in s.text]
    assert flags and flags[0].claim_ids == ("c9",)


def test_no_web_presence_and_gaps_name_data() -> None:
    out = sigs()
    assert any("No web presence" in t for t in kinds(out, SignalKind.red_flag))
    gaps = kinds(out, SignalKind.gap)
    assert len(gaps) == 6 and all("Needs" in g for g in gaps)
    assert any("competitor list" in g for g in gaps)


def test_self_reported_only_is_gap() -> None:
    out = sigs(DOMAIN, Item("c1", "headcount", 10, date(2026, 3, 1)),
               Item("c2", "headcount", 20, date(2026, 10, 1)))
    assert any("traction rests only on self-reported" in g for g in kinds(out, SignalKind.gap))


@pytest.mark.parametrize(("kwargs", "action"), [
    ({"score": 90, "exclusion": "crypto"}, SuggestedAction.pass_),
    ({"score": 70, "completeness": 0.8}, SuggestedAction.reach_out),
    ({"score": 70, "completeness": 0.3}, SuggestedAction.request_data),
    ({"score": 70, "completeness": 0.8, "red_flags": 1}, SuggestedAction.request_data),
    ({"score": 50}, SuggestedAction.watch),
    ({"score": 30}, SuggestedAction.pass_),
    ({"score": 70, "status": CandidateStatus.in_dd, "dd_stage": DDStage.ready_for_decision,
      "red_flags": 1}, SuggestedAction.invest),
    ({"score": None, "completeness": 0.0}, SuggestedAction.request_data),
    ({"score": 70, "completeness": 0.8, "red_flags": 1, "has_deck": True},
     SuggestedAction.watch),
])
def test_action_table(kwargs: dict[str, Any], action: SuggestedAction) -> None:
    args: dict[str, Any] = {"completeness": 0.8, "exclusion": None, "thresholds": THRESH}
    got, reason = suggest(**(args | kwargs))
    assert got == action and reason
