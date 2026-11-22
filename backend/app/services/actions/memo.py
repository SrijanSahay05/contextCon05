"""Investment memo: the citation post-check, ref rendering, and the request/read paths.

The LLM cites evidence as `[f:<fact id>]` / `[c:<claim id>]`. `post_check` drops every
sentence whose numbers or dates are not in the items it cites; `render_refs` then swaps
the markers for the `[n]` refs the API returns.
"""

import json
import math
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.actions import Memo
from app.models.enums import RunKind
from app.models.runs import Job
from app.models.search import Candidate, Search
from app.repositories import scores
from app.schemas.common import RunAccepted
from app.schemas.memo import MemoOut
from app.services.jobs import queue
from app.services.onboarding.firm import accepted

JOB_KIND = "memo"

# --- extracting numbers and dates ------------------------------------------------------

_MONTH = r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}
# most specific first; each match is blanked out before numbers are read
_DATES = [
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})(?:-(?P<d>\d{2}))?\b"),
    re.compile(rf"\b(?P<d>\d{{1,2}})\s+{_MONTH},?\s+(?P<y>\d{{4}})\b", re.I),
    re.compile(rf"\b{_MONTH}\s+(?P<d>\d{{1,2}}),?\s+(?P<y>\d{{4}})\b", re.I),
    re.compile(rf"\b{_MONTH}\s+(?P<y>\d{{4}})\b", re.I),
]
_NUMBER = re.compile(
    r"(?<![\w.])[$₹€£]?(?P<n>\d{1,3}(?:,\d{3})+|\d+)(?P<f>\.\d+)?\s*"
    r"(?P<u>%|percent\b|k\b|thousand\b|mn?\b|million\b|bn?\b|billion\b|cr\b|crores?\b"
    r"|lakhs?\b)?",
    re.I,
)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9,
          "bn": 1e9, "billion": 1e9, "cr": 1e7, "crore": 1e7, "crores": 1e7, "lakh": 1e5,
          "lakhs": 1e5}


@dataclass
class Tokens:
    numbers: list[tuple[float, bool, str]] = field(default_factory=list)  # value, is_pct, text
    dates: list[str] = field(default_factory=list)  # "YYYY-MM" or "YYYY-MM-DD"


def extract(text: str) -> Tokens:
    """Numbers (`1,425`, `$9M`, `9 million`, `90%`) and dates (ISO, `Aug 2026`)."""
    out = Tokens()
    for pattern in _DATES:
        def take(m: re.Match[str]) -> str:
            g = m.groupdict()
            month = int(g["m"]) if g.get("m") else _MONTHS[g["mon"].lower()]
            day = f"-{int(g['d']):02d}" if g.get("d") else ""
            out.dates.append(f"{g['y']}-{month:02d}{day}")
            return " "
        text = pattern.sub(take, text)
    for m in _NUMBER.finditer(text):
        value = float(m.group("n").replace(",", "") + (m.group("f") or ""))
        unit = (m.group("u") or "").lower()
        value *= _SCALE.get(unit, 1)
        out.numbers.append((value, unit in ("%", "percent"), m.group(0).strip()))
    return out


def _walk(value: Any, out: Tokens) -> None:
    """Numbers and dates anywhere in a stored JSON value (dict keys are labels, skipped)."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.numbers.append((float(value), False, str(value)))
    elif isinstance(value, str):
        found = extract(value)
        out.numbers += found.numbers
        out.dates += found.dates
    elif isinstance(value, dict):
        for v in value.values():
            _walk(v, out)
    elif isinstance(value, list):
        for v in value:
            _walk(v, out)


def support(items: list[dict[str, Any]]) -> tuple[list[float], set[str]]:
    """What the cited items can back: their numbers, and their dates down to the month
    (and year, as a number)."""
    found = Tokens()
    for item in items:
        _walk(item.get("value"), found)
        _walk(item.get("as_of"), found)
    numbers = [n for n, _, _ in found.numbers]
    dates: set[str] = set()
    for iso in found.dates:
        dates |= {iso, iso[:7]}
        numbers.append(float(iso[:4]))
    return numbers, dates


def _backed(token: tuple[float, bool, str], numbers: list[float]) -> bool:
    value, pct, _ = token
    wanted = [value, value / 100] if pct else [value]  # 90% may be stored as 0.9
    return any(math.isclose(w, n, rel_tol=1e-9) for w in wanted for n in numbers)


# --- the post-check --------------------------------------------------------------------

_CITE = re.compile(r"\[\s*[fc]:[^\]]*\]")
_CITE_ID = re.compile(r"([fc]):\s*([\w-]+)")
_BULLET = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)")
# split after . ! ? unless the next thing is a citation that belongs to this sentence
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?!\[\s*[fc]:)")


def cited_ids(sentence: str) -> list[str]:
    return [f"{kind}:{ref}" for marker in _CITE.findall(sentence)
            for kind, ref in _CITE_ID.findall(marker)]


def check_sentence(sentence: str, evidence: dict[str, dict[str, Any]]) -> str | None:
    """Why the sentence must go, or None if it stays."""
    ids = cited_ids(sentence)
    unknown = [i for i in ids if i not in evidence]
    if unknown:
        return f"unsupported: cites unknown evidence {', '.join(unknown)}"
    tokens = extract(_CITE.sub(" ", sentence))
    if not tokens.numbers and not tokens.dates:
        return None
    if not ids:
        return "unsupported: states a number or date without a citation"
    numbers, dates = support([evidence[i] for i in ids])
    missing = [d for d in tokens.dates if d not in dates]
    missing += [t[2] for t in tokens.numbers if not _backed(t, numbers)]
    if missing:
        return f"unsupported: {', '.join(missing)} not in the cited evidence"
    return None


def post_check(markdown: str, evidence: dict[str, dict[str, Any]]
               ) -> tuple[str, list[dict[str, str]]]:
    """Drop unsupported sentences; returns the kept markdown and `{text, reason}` removals.
    Headings are kept as written."""
    removed: list[dict[str, str]] = []
    lines: list[str] = []
    for line in markdown.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            lines.append(line)
            continue
        bullet = _BULLET.match(line)
        prefix = bullet.group(1) if bullet else ""
        kept = []
        for sentence in _SENTENCE_END.split(line[len(prefix):].strip()):
            reason = check_sentence(sentence, evidence)
            if reason:
                removed.append({"text": sentence, "reason": reason})
            else:
                kept.append(sentence)
        if kept:
            lines.append(prefix + " ".join(kept))
    return "\n".join(lines), removed


def render_refs(markdown: str) -> tuple[str, list[str]]:
    """`[f:1][c:x]` → `[1][2]`, numbered by first use; returns the ids in ref order."""
    order: list[str] = []

    def ref(marker: re.Match[str]) -> str:
        refs = []
        for kind, raw in _CITE_ID.findall(marker.group(0)):
            key = f"{kind}:{raw}"
            if key not in order:
                order.append(key)
            refs.append(f"[{order.index(key) + 1}]")
        return "".join(refs)

    return _CITE.sub(ref, markdown), order


def evidence_line(n: int, item: dict[str, Any]) -> str:
    extra = f"; verification: {item['verification']}" if item.get("verification") else ""
    return (f"{n}. [{item['key']}] {item['predicate']} = {json.dumps(item['value'])} "
            f"(as of {item['as_of'] or 'unknown'}; source: {item['citation']['kind']}{extra})")


# --- request and read ------------------------------------------------------------------

def request(db: Session, candidate_id: uuid.UUID, investor_id: uuid.UUID) -> RunAccepted:
    """A run per (candidate, latest score snapshot): re-asking on unchanged data returns
    the same run."""
    candidate = scores.get_owned(db, candidate_id, investor_id)
    history = scores.snapshots(db, candidate.id)
    key = f"{JOB_KIND}:{candidate.id}:{history[-1].id if history else 'none'}"
    existing = db.scalar(select(Job).where(Job.idempotency_key == key))
    if existing is not None and existing.run_id is not None:
        return accepted(existing.run_id)
    subject = {"candidate_id": str(candidate.id), "investor_id": str(investor_id)}
    run = queue.create_run(db, RunKind.memo, subject)
    queue.enqueue(db, JOB_KIND, subject, key, run.id)
    db.commit()
    return accepted(run.id)


def get(db: Session, memo_id: uuid.UUID, investor_id: uuid.UUID) -> MemoOut:
    memo = db.scalar(
        select(Memo).join(Candidate, Candidate.id == Memo.candidate_id)
        .join(Search, Search.id == Candidate.search_id)
        .where(Memo.id == memo_id, Search.investor_id == investor_id)
    )
    if memo is None:
        raise ApiError(404, ErrorCode.not_found, "Memo not found")
    return MemoOut.model_validate({
        "id": memo.id, "candidate_id": memo.candidate_id, "version": memo.version,
        "markdown": memo.markdown, "citations": memo.citations, "removed": memo.removed,
        "stale": memo.stale, "generated_at": memo.generated_at,
    })
