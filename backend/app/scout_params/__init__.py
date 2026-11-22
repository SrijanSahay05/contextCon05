"""Scout run parameters: schemas, signal registry, lens presets, weights.

Import from `app.scout_params`. Design reference: docs/prd/scout_params.md.
"""

from .defaults import default_request, load_defaults
from .enums import (
    BusinessModel,
    Category,
    ClaimVerdict,
    Decision,
    EvidenceKind,
    KillRule,
    Lens,
    Origin,
    Relationship,
    RepeatFounderPref,
    Stage,
)
from .lenses import LENS_CATEGORY_WEIGHTS, lens_base_weights
from .models import (
    SCHEMA_VERSION,
    DecisionThresholds,
    EvidenceRef,
    FounderPreferences,
    InferenceConfig,
    InvestorIdentity,
    InvestorProfile,
    KillThresholds,
    PortfolioStats,
    PostTheme,
    Ranking,
    ResolvedIdentity,
    RunControls,
    ScoutRequest,
    SignalThresholds,
    Thesis,
    Weight,
)
from .signals import PROTECTED_INPUTS, SIGNALS, SignalKey, SignalSpec
from .weights import (
    SignalNudge,
    infer_weights,
    lens_weights,
    panel_order,
    reset_weights,
    set_locked,
    set_weight,
)

__all__ = [
    "BusinessModel", "Category", "ClaimVerdict", "Decision",
    "DecisionThresholds", "EvidenceKind", "EvidenceRef",
    "FounderPreferences", "InferenceConfig", "InvestorIdentity",
    "InvestorProfile", "KillRule", "KillThresholds", "LENS_CATEGORY_WEIGHTS",
    "Lens", "Origin", "PROTECTED_INPUTS", "PortfolioStats", "PostTheme",
    "Ranking", "Relationship", "RepeatFounderPref", "ResolvedIdentity",
    "RunControls", "SCHEMA_VERSION", "SIGNALS", "ScoutRequest",
    "SignalKey", "SignalNudge", "SignalSpec", "SignalThresholds", "Stage",
    "Thesis", "Weight", "default_request", "infer_weights",
    "lens_base_weights", "lens_weights", "load_defaults", "panel_order",
    "reset_weights", "set_locked", "set_weight",
]
