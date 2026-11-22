"""Factories and config loading.

Everything likely to change at hour 3 (limits, thresholds, inference caps)
lives in `defaults.json`, so a requirement change is a one-line edit there.
"""

import json
from importlib import resources
from pathlib import Path
from typing import Any

from .enums import Lens
from .models import InvestorIdentity, Ranking, ScoutRequest, Thesis
from .weights import lens_weights


def load_defaults(path: str | Path | None = None) -> dict[str, Any]:
    """Load the defaults file (packaged one unless `path` is given)."""

    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (
            resources.files(__package__)
            .joinpath("defaults.json")
            .read_text(encoding="utf-8")
        )
    data: dict[str, Any] = json.loads(text)
    return data


def _ranking(defaults: dict[str, Any], lens: Lens) -> Ranking:
    cfg = dict(defaults.get("ranking", {}))
    cfg["lens"] = lens
    cfg["weights"] = [w.model_dump() for w in lens_weights(lens)]
    return Ranking.model_validate(cfg)


def default_request(
    *,
    investor: InvestorIdentity | None = None,
    thesis_text: str | None = None,
    thesis: Thesis | None = None,
    lens: Lens | None = None,
    defaults: dict[str, Any] | None = None,
) -> ScoutRequest:
    """Build a valid request from config defaults plus whatever was given."""

    d = defaults if defaults is not None else load_defaults()
    chosen = lens or Lens(d.get("ranking", {}).get("lens", Lens.PRE_ROUND))
    payload: dict[str, Any] = {
        "thesis": (thesis.model_dump() if thesis else d.get("thesis", {})),
        "signals": d.get("signals", {}),
        "founders": d.get("founders", {}),
        "decision": d.get("decision", {}),
        "run": d.get("run", {}),
        "ranking": _ranking(d, chosen).model_dump(),
        "thesis_text": thesis_text,
        "investor": investor.model_dump() if investor else None,
    }
    return ScoutRequest.model_validate(payload)
