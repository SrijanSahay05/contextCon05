"""The suggested-action table: evaluated in order, the first match wins. Pure.

Order differs from the PRD table in one place: `invest` is checked right after the
exclusion, since its condition (in DD, ready, score ≥ reach_out) is a narrower case of
the `reach_out`/`request_data` rows and would otherwise never fire.
"""

from typing import Any

from app.models.enums import CandidateStatus, DDStage, SuggestedAction


def suggest(
    *,
    score: float | None,
    completeness: float,
    exclusion: str | None,
    thresholds: dict[str, Any],
    red_flags: int = 0,
    has_deck: bool = False,
    status: CandidateStatus = CandidateStatus.new,
    dd_stage: DDStage | None = None,
    unmet: tuple[str, ...] = (),
) -> tuple[SuggestedAction, str]:
    """`unmet`: requirements the search asked for that no fact verifies (e.g. a grant)."""
    reach, watch = float(thresholds["reach_out"]), float(thresholds["watch"])
    min_complete = float(thresholds["min_completeness"])
    if exclusion:
        return SuggestedAction.pass_, f"Thesis exclusion: {exclusion}"
    if score is None:
        return SuggestedAction.request_data, "No evidence on any criterion yet"
    if (status == CandidateStatus.in_dd and dd_stage == DDStage.ready_for_decision
            and score >= reach):
        return SuggestedAction.invest, f"DD complete and score {score:g} ≥ {reach:g}"
    if score >= reach and unmet:
        return SuggestedAction.request_data, (
            f"Score {score:g} ≥ {reach:g}, but the search requires {', '.join(unmet)} "
            "and no source verifies it: ask the founders")
    if score >= reach and completeness >= min_complete and not red_flags:
        return SuggestedAction.reach_out, f"Score {score:g} ≥ {reach:g} with " \
            f"{completeness:.0%} of the evidence and no red flags"
    if score >= reach and (completeness < min_complete or not has_deck):
        why = (f"only {completeness:.0%} of the evidence is known"
               if completeness < min_complete else "no deck yet")
        return SuggestedAction.request_data, f"Score {score:g} is high but {why}"
    if watch <= score < reach:
        return SuggestedAction.watch, f"Score {score:g} between {watch:g} and {reach:g}"
    if score < watch:
        return SuggestedAction.pass_, f"Score {score:g} below {watch:g}"
    # high score, complete, deck in hand, but red flags still open
    return SuggestedAction.watch, f"Score {score:g} is high but {red_flags} red flag(s) " \
        "are unresolved"
