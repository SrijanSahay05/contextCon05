"""Founder claims from document pages: LLM extraction, kept only when the quote is on its page.

Predicates match the fact predicates (`facts_mapper`) so verification can compare them;
revenue, ARR, customers and burn have no public source and stay self-reported.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.integrations.llm import quote_check
from app.services.clients import Clients
from app.services.evidence import facts_mapper as fm

REVENUE_USD = "revenue_usd"
ARR_USD = "arr_usd"
CUSTOMERS = "customers"
BURN_USD = "burn_usd"
NUMERIC = {fm.HEADCOUNT_TOTAL, fm.FUNDING_TOTAL_USD, fm.YEAR_FOUNDED,
           REVENUE_USD, ARR_USD, CUSTOMERS, BURN_USD}
PREDICATES = NUMERIC | {fm.FUNDING_ROUND, fm.LAST_ROUND_TYPE, fm.FOUNDER, fm.EMPLOYMENT,
                        fm.EDUCATION, "grant", fm.HQ_COUNTRY}
BATCH_CHARS = 12000

SYSTEM = f"""You extract factual claims a startup makes about itself from its documents.
Extract only concrete, checkable statements: team size, funding raised and rounds, founders'
backgrounds (past employers, schools), grants, revenue, ARR, customers, burn, HQ country,
founding year. Skip opinions, market sizes and plans.

For each claim give:
- predicate: one of {", ".join(sorted(PREDICATES))}
  (headcount_total = total team size; customers = number of paying customers;
  founder = {{"name", "title"}}; employment = {{"name" (person), "title", "company_name",
  "start", "end"}}; education = {{"name" (person), "school", "degree", "field"}};
  funding_round = {{"round_type", "amount_usd", "investors"}}; grant = {{"name", "amount"}})
- value: a number for counts and money (USD, e.g. "$4.5M" -> 4500000), else a string or object
- as_of: the date the claim refers to as YYYY-MM-DD or YYYY-MM, only if stated
- page: the page number the quote is on
- quote: the exact words from that page that state the claim, copied verbatim"""


class ClaimItem(BaseModel):
    predicate: str
    value: Any
    as_of: str | None = None
    page: int
    quote: str


class ClaimList(BaseModel):
    claims: list[ClaimItem]


@dataclass(frozen=True)
class ClaimDraft:
    predicate: str
    value: Any
    as_of: date | None
    page: int
    quote: str


_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
          "b": 1e9, "bn": 1e9, "billion": 1e9}
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(thousand|million|billion|mn|bn|k|m|b)?\b", re.I)


def to_number(value: Any) -> int | float | None:
    """`40`, "40 engineers" → 40; "$4.5M" → 4500000; anything without a number → None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = _NUMBER.search(str(value).replace(",", ""))
        if match is None:
            return None
        number = float(match.group(1)) * _SCALE.get((match.group(2) or "").lower(), 1)
    return int(number) if number.is_integer() else number


def _as_of(value: str | None) -> date | None:
    if value and re.fullmatch(r"\d{4}-\d{2}", value):
        value += "-01"
    return fm.parse_date(value)


def _normalise(item: ClaimItem) -> ClaimDraft | None:
    if item.predicate not in PREDICATES:
        return None
    value = item.value
    if item.predicate in NUMERIC:
        value = to_number(value)
    elif isinstance(value, dict) and "amount_usd" in value:
        value = {**value, "amount_usd": to_number(value["amount_usd"])}
    if value is None or value == "":
        return None
    return ClaimDraft(item.predicate, value, _as_of(item.as_of), item.page, item.quote)


def _batches(pages: list[str]) -> list[list[int]]:
    """Consecutive non-empty page numbers (1-based), up to BATCH_CHARS of text per batch."""
    batches: list[list[int]] = []
    size = BATCH_CHARS
    for number, text in enumerate(pages, start=1):
        if not text.strip():
            continue
        if size + len(text) > BATCH_CHARS:
            batches.append([])
            size = 0
        batches[-1].append(number)
        size += len(text)
    return batches


def extract_claims(clients: Clients, pages: list[str]) -> list[ClaimDraft]:
    drafts: list[ClaimDraft] = []
    for batch in _batches(pages):
        prompt = "\n\n".join(f"--- page {n} ---\n{pages[n - 1]}" for n in batch)
        result = clients.llm.extract(ClaimList, SYSTEM, prompt)
        for item in result.claims:
            if item.page not in batch or not quote_check(pages[item.page - 1], item.quote):
                continue  # the quote isn't on the page it cites: drop it, never guess
            draft = _normalise(item)
            if draft is not None:
                drafts.append(draft)
    return drafts
