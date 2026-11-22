"""Lens presets: category weights that are split across signals by `share`."""

from .enums import Category, Lens
from .signals import SignalKey, signals_in

LENS_CATEGORY_WEIGHTS: dict[Lens, dict[Category, float]] = {
    Lens.PRE_ROUND: {
        Category.FOUNDER: 30, Category.TRACTION: 30,
        Category.TIMING: 30, Category.MARKET: 10,
    },
    Lens.MOMENTUM: {
        Category.FOUNDER: 20, Category.TRACTION: 50,
        Category.TIMING: 15, Category.MARKET: 15,
    },
    Lens.FOUNDER_FIRST: {
        Category.FOUNDER: 50, Category.TRACTION: 25,
        Category.TIMING: 15, Category.MARKET: 10,
    },
    Lens.STRATEGIC_FIT: {
        Category.FOUNDER: 25, Category.TRACTION: 25,
        Category.TIMING: 15, Category.MARKET: 35,
    },
}


def lens_base_weights(lens: Lens) -> dict[SignalKey, float]:
    """Per-signal base weights for a lens; sums to 100."""

    out: dict[SignalKey, float] = {}
    for category, cat_weight in LENS_CATEGORY_WEIGHTS[lens].items():
        specs = signals_in(category)
        total_share = sum(s.share for s in specs)
        for s in specs:
            out[s.key] = cat_weight * s.share / total_share
    return out
