"""Which documents to ask the founder for, from what the score could not establish.

Keyed by the criterion's rule (not its key), so derived profiles with renamed criteria
map the same way.
"""

from typing import Any

from app.models.enums import DDItemKind as K
from app.services.scoring.rules import UNKNOWN

RULE_ITEMS: dict[str, tuple[K, ...]] = {
    "growth_signals": (K.financials, K.data_room),
    "capital_efficiency": (K.financials, K.data_room),
    "team_signals": (K.answer,),
    "technical_depth": (K.answer,),
    "funding_stage_fit": (K.cap_table, K.grant_letter),
    "market_signals": (K.customer_refs,),
}
LABELS = {
    K.deck: "Latest pitch deck",
    K.data_room: "Data room access",
    K.financials: "Financials (P&L, monthly revenue and burn)",
    K.cap_table: "Current cap table",
    K.grant_letter: "Grant award letters",
    K.customer_refs: "Customer references",
    K.answer: "Answers to a few questions about the team",
}


def gap_items(breakdown: list[dict[str, Any]], gap_texts: list[str], has_deck: bool
              ) -> list[tuple[K, str]]:
    """(kind, reason) per item to request, one per kind, in checklist order."""
    out: dict[K, str] = {}
    if not has_deck:
        out[K.deck] = "No deck on file"
    for c in breakdown:
        if c.get("score") != UNKNOWN and not c.get("self_reported_only"):
            continue
        # the gap signal says why; fall back to the criterion's own reason
        reason = next((t for t in gap_texts if t.startswith(f"{c['key']} ")),
                      f"{c['key']}: {c.get('reason', 'unknown')}")
        for kind in RULE_ITEMS.get(c.get("rule", ""), ()):
            out.setdefault(kind, reason)
    return list(out.items())
