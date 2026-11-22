"""Deterministic weight logic: inference, slider rebalancing, panel order.

The LLM never sets weights. It only tags posts; this module turns tagged
deltas and portfolio statistics into weights, with caps, and records why.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .enums import Lens, Origin
from .lenses import lens_base_weights
from .models import (
    WEIGHT_TOTAL,
    EvidenceRef,
    InferenceConfig,
    Weight,
)
from .signals import SIGNALS, SignalKey


@dataclass
class SignalNudge:
    """A proposed change to one signal, from the portfolio or from posts.

    `strength` is unitless in [-1, 1]; it is scaled by `max_delta` and the
    alpha/beta pull before being applied.
    """

    signal: SignalKey
    strength: float
    reason: str
    evidence: list[EvidenceRef] = field(default_factory=list)


def _capped_normalize(
    raw: Mapping[SignalKey, float],
    fixed: Mapping[SignalKey, float],
    lo: float,
    hi: float,
    total: float = WEIGHT_TOTAL,
) -> dict[SignalKey, float]:
    """Scale free weights so all weights sum to `total`, each in [lo, hi].

    `fixed` weights are kept as-is. Free weights hitting a bound are pinned
    and the rest re-scaled (water-filling) until stable.
    """

    out = dict(fixed)
    free = {k: max(v, 0.0) for k, v in raw.items() if k not in fixed}
    # each pass either finishes or pins at least one weight, so it ends
    while free:
        remaining = total - sum(out.values())
        s = sum(free.values())
        if s <= 0:
            scaled = {k: remaining / len(free) for k in free}
        else:
            scaled = {k: v * remaining / s for k, v in free.items()}
        pinned = {
            k: (hi if v > hi else lo)
            for k, v in scaled.items()
            if v > hi or v < lo
        }
        if not pinned:
            out.update(scaled)
            break
        out.update(pinned)
        for k in pinned:
            del free[k]
    return _fix_rounding(out, locked=set(fixed), total=total, lo=lo, hi=hi)


def _fix_rounding(
    w: dict[SignalKey, float],
    locked: set[SignalKey],
    total: float,
    lo: float = 0.0,
    hi: float = WEIGHT_TOTAL,
) -> dict[SignalKey, float]:
    """Round to 2dp and put the residual on the largest weight that can
    absorb it without leaving [lo, hi] (never on a locked weight)."""

    rounded = {k: round(v, 2) for k, v in w.items()}
    residual = round(total - sum(rounded.values()), 2)
    if residual:
        unlocked = [k for k in rounded if k not in locked] or list(rounded)
        fits = [
            k for k in unlocked if lo <= rounded[k] + residual <= hi
        ] or unlocked
        target = max(fits, key=lambda k: rounded[k])
        rounded[target] = round(rounded[target] + residual, 2)
    return rounded


def lens_weights(lens: Lens) -> list[Weight]:
    base = _fix_rounding(lens_base_weights(lens), set(), WEIGHT_TOTAL)
    return [
        Weight(signal=k, value=v, base=v, origin=Origin.LENS_DEFAULT)
        for k, v in base.items()
    ]


def infer_weights(
    lens: Lens,
    portfolio_nudges: Iterable[SignalNudge] = (),
    post_nudges: Iterable[SignalNudge] = (),
    config: InferenceConfig | None = None,
) -> list[Weight]:
    """w = normalize(w_lens + alpha*delta_portfolio + beta*delta_posts)."""

    cfg = config or InferenceConfig()
    base = lens_base_weights(lens)
    raw = dict(base)
    reasons: dict[SignalKey, list[str]] = {}
    evidence: dict[SignalKey, list[EvidenceRef]] = {}

    for pull, nudges in ((cfg.alpha, portfolio_nudges), (cfg.beta, post_nudges)):
        for n in nudges:
            spec = SIGNALS[n.signal]
            if not spec.inferable:
                continue
            strength = max(-1.0, min(1.0, n.strength))
            raw[n.signal] += pull * strength * cfg.max_delta
            reasons.setdefault(n.signal, []).append(n.reason)
            evidence.setdefault(n.signal, []).extend(n.evidence)

    # clamp each move to max_delta around the lens base
    for k in raw:
        lo_k, hi_k = base[k] - cfg.max_delta, base[k] + cfg.max_delta
        raw[k] = min(max(raw[k], lo_k), hi_k)

    final = _capped_normalize(raw, {}, cfg.min_weight, cfg.max_weight)
    base_r = _fix_rounding(base, set(), WEIGHT_TOTAL)
    return [
        Weight(
            signal=k,
            value=final[k],
            base=base_r[k],
            origin=Origin.INFERRED if k in reasons else Origin.LENS_DEFAULT,
            evidence=evidence.get(k, []),
            reason="; ".join(reasons[k]) if k in reasons else None,
        )
        for k in base
    ]


def set_weight(
    weights: list[Weight], signal: SignalKey, value: float
) -> list[Weight]:
    """Apply an investor slider move; rebalance unlocked others to 100.

    The moved weight is marked INVESTOR and stays exactly at `value`
    (clipped to what the locked weights leave). Others scale
    proportionally.
    """

    by_key = {w.signal: w for w in weights}
    if signal not in by_key:
        raise KeyError(signal)
    locked_total = sum(
        w.value for w in weights if w.locked and w.signal != signal
    )
    value = max(0.0, min(value, WEIGHT_TOTAL - locked_total))
    fixed = {w.signal: w.value for w in weights if w.locked}
    fixed[signal] = value
    raw = {w.signal: w.value for w in weights}
    new = _capped_normalize(raw, fixed, 0.0, WEIGHT_TOTAL)
    out = []
    for w in weights:
        changes: dict[str, object] = {"value": new[w.signal]}
        if w.signal == signal:
            changes["origin"] = Origin.INVESTOR
        out.append(w.model_copy(update=changes))
    return out


def set_locked(
    weights: list[Weight], signal: SignalKey, locked: bool
) -> list[Weight]:
    return [
        w.model_copy(update={"locked": locked}) if w.signal == signal else w
        for w in weights
    ]


def reset_weights(weights: list[Weight]) -> list[Weight]:
    """Back to the lens base for every unlocked weight."""

    fixed = {w.signal: w.value for w in weights if w.locked}
    raw = {w.signal: w.base for w in weights}
    new = _capped_normalize(raw, fixed, 0.0, WEIGHT_TOTAL)
    return [
        w if w.locked else w.model_copy(
            update={
                "value": new[w.signal],
                "origin": Origin.LENS_DEFAULT,
                "reason": None,
                "evidence": [],
            }
        )
        for w in weights
    ]


def panel_order(weights: list[Weight], top_n: int | None = None) -> list[Weight]:
    """Most influential first: by value, then by how far it moved."""

    ordered = sorted(
        weights, key=lambda w: (w.value, abs(w.delta)), reverse=True
    )
    return ordered[:top_n] if top_n else ordered
