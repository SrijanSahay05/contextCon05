"""Pydantic models for a scout run's parameters.

Layout mirrors the design:
  Group 0  investor identity (+ resolved identity, inferred profile)
  Group A  thesis (hard gates)
  Group B  signal thresholds (soft gates)
  Group C  ranking (lens, weights, inference config, kill rules)
  Group D  founder preferences
  Group E  run controls (budgets, limits, as-of date)
Every model forbids unknown keys, so a protected field (e.g. "college")
cannot slip in unnoticed.
"""

import re
from datetime import date
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .enums import (
    BusinessModel,
    EvidenceKind,
    KillRule,
    Lens,
    Origin,
    Relationship,
    RepeatFounderPref,
    Stage,
)
from .signals import PROTECTED_INPUTS, SignalKey

SCHEMA_VERSION = "1.0"
WEIGHT_TOTAL = 100.0
WEIGHT_TOLERANCE = 0.05

_LINKEDIN_PROFILE = re.compile(
    r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?$"
)
_ISO3 = re.compile(r"^[A-Z]{3}$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_protected_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            hit = PROTECTED_INPUTS.intersection(
                str(k).lower() for k in data
            )
            if hit:
                raise ValueError(
                    f"protected attribute(s) not allowed: {sorted(hit)}. "
                    "These are proxies for protected traits and are "
                    "excluded by design."
                )
        return data


# ---------------------------------------------------------------- evidence


class EvidenceRef(_Model):
    """Points at the exact record behind an inference or a fact."""

    kind: EvidenceKind
    ref: str = Field(description="URL, field path, or ledger fact id")
    record_date: date | None = None
    note: str | None = None


# ---------------------------------------------------------------- group 0


class InvestorIdentity(_Model):
    """The only inputs the investor must type."""

    name: str = Field(min_length=2, max_length=120)
    firm: str = Field(min_length=2, max_length=160)
    linkedin_url: str
    consent: bool = Field(
        description="Consent to analyse their public professional profile "
        "and posts. Must be true."
    )
    hint: str | None = Field(
        default=None,
        max_length=300,
        description="Optional one-liner that overrides inference, e.g. "
        "'logistics only'.",
    )

    @field_validator("linkedin_url")
    @classmethod
    def _linkedin(cls, v: str) -> str:
        v = v.strip().split("?")[0]
        if not _LINKEDIN_PROFILE.match(v):
            raise ValueError("must be a linkedin.com/in/<handle> profile URL")
        return v.rstrip("/")

    @field_validator("consent")
    @classmethod
    def _consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("consent is required to profile the investor")
        return v


class ResolvedIdentity(_Model):
    """Filled after Person Enrich + Company Identify; never typed."""

    person_id: str | None = None
    firm_company_id: str | None = None
    name_matches_profile: bool | None = None
    firm_matches_profile: bool | None = None
    confirmed_by_user: bool = False

    @property
    def needs_confirmation(self) -> bool:
        return not self.confirmed_by_user and (
            self.person_id is None
            or self.firm_company_id is None
            or self.name_matches_profile is False
            or self.firm_matches_profile is False
        )


class PostTheme(_Model):
    theme: str
    count: int = Field(ge=0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PortfolioStats(_Model):
    """Computed deterministically from the firm's portfolio companies."""

    sampled: int = Field(ge=0)
    company_ids: list[str] = Field(default_factory=list)
    stage_mix: dict[Stage, float] = Field(default_factory=dict)
    sector_mix: dict[str, float] = Field(default_factory=dict)
    hq_mix: dict[str, float] = Field(default_factory=dict)
    tech_cofounder_share: float | None = Field(default=None, ge=0, le=1)
    repeat_founder_share: float | None = Field(default=None, ge=0, le=1)
    median_headcount_at_round: float | None = Field(default=None, ge=0)
    median_growth_6m_before_round: float | None = None


class InvestorProfile(_Model):
    post_themes: list[PostTheme] = Field(default_factory=list)
    posts_analysed: int = Field(default=0, ge=0)
    portfolio: PortfolioStats | None = None
    cold_start: bool = Field(
        default=False,
        description="True when posts/portfolio were too thin; lens "
        "defaults were used.",
    )
    cold_start_reason: str | None = None


# ---------------------------------------------------------------- group A


class Thesis(_Model):
    industries: list[str] = Field(
        default_factory=list,
        description="Exact values from Crustdata autocomplete.",
    )
    subsectors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    business_models: list[BusinessModel] = Field(
        default_factory=lambda: [BusinessModel.B2B_SAAS]
    )
    hq_countries: list[str] = Field(default_factory=lambda: ["IND"])
    include_india_built_us_hq: bool = True
    founded_from: int | None = Field(default=None, ge=1990, le=2100)
    founded_to: int | None = Field(default=None, ge=1990, le=2100)
    stages: list[Stage] = Field(default_factory=list)
    headcount_min: int = Field(default=5, ge=1)
    headcount_max: int | None = Field(default=None, ge=1)
    relationship: Relationship = Relationship.INVESTMENT
    exclude_domains: list[str] = Field(default_factory=list)
    exclude_company_ids: list[str] = Field(default_factory=list)
    exclude_portfolio_competitors: bool = False
    field_origins: dict[str, Origin] = Field(
        default_factory=dict,
        description="Per-field provenance: lens_default | inferred | "
        "investor.",
    )

    @field_validator("hq_countries")
    @classmethod
    def _iso3(cls, v: list[str]) -> list[str]:
        out = [c.strip().upper() for c in v]
        bad = [c for c in out if not _ISO3.match(c)]
        if bad:
            raise ValueError(f"hq_countries must be ISO3 codes, got {bad}")
        return out

    @field_validator("exclude_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        return [
            d.strip().lower().removeprefix("https://")
            .removeprefix("http://").removeprefix("www.").rstrip("/")
            for d in v
        ]

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        if (
            self.founded_from is not None
            and self.founded_to is not None
            and self.founded_from > self.founded_to
        ):
            raise ValueError("founded_from must be <= founded_to")
        if (
            self.headcount_max is not None
            and self.headcount_min > self.headcount_max
        ):
            raise ValueError("headcount_min must be <= headcount_max")
        return self


# ---------------------------------------------------------------- group B


class SignalThresholds(_Model):
    growth_6m_min: float | None = Field(
        default=0.5, description="0.5 = +50%, recomputed from timeseries."
    )
    growth_min_base_headcount: int = Field(
        default=5, ge=1, description="Floor so 2->3 is not '50% growth'."
    )
    months_since_round_min: int | None = Field(default=12, ge=0)
    total_raised_usd_min: float | None = Field(default=None, ge=0)
    total_raised_usd_max: float | None = Field(default=None, ge=0)
    min_coverage: float = Field(
        default=0.6,
        ge=0,
        le=1,
        description="Below this share of signals present -> CANNOT_VERIFY.",
    )


# ---------------------------------------------------------------- group C


class Weight(_Model):
    signal: SignalKey
    value: float = Field(ge=0, le=WEIGHT_TOTAL)
    base: float = Field(ge=0, le=WEIGHT_TOTAL, description="Lens default.")
    origin: Origin = Origin.LENS_DEFAULT
    locked: bool = False
    evidence: list[EvidenceRef] = Field(default_factory=list)
    reason: str | None = Field(
        default=None, description="One-line 'why' shown in the panel."
    )

    @property
    def delta(self) -> float:
        return self.value - self.base


class InferenceConfig(_Model):
    alpha: float = Field(default=0.6, ge=0, description="Portfolio pull.")
    beta: float = Field(default=0.4, ge=0, description="Posts pull.")
    min_weight: float = Field(default=0.0, ge=0)
    max_weight: float = Field(
        default=35.0,
        gt=0,
        le=WEIGHT_TOTAL,
        description="Cap for inferred weights; investor overrides may "
        "exceed it.",
    )
    max_delta: float = Field(
        default=15.0, ge=0, description="Max points one signal may move."
    )

    @property
    def excluded_inputs(self) -> frozenset[str]:
        """Fixed by design; not configurable."""

        return PROTECTED_INPUTS


class KillThresholds(_Model):
    headcount_drop_pct: float = Field(default=0.30, gt=0, le=1)
    claim_mismatch_ratio: float = Field(
        default=0.5,
        gt=0,
        description="|claimed-actual|/actual above which a claim kills.",
    )


class Ranking(_Model):
    lens: Lens = Lens.PRE_ROUND
    weights: list[Weight]
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    panel_top_n: int = Field(default=5, ge=1, le=25)
    kills: list[KillRule] = Field(default_factory=lambda: list(KillRule))
    kill_thresholds: KillThresholds = Field(default_factory=KillThresholds)

    @model_validator(mode="after")
    def _weights_valid(self) -> Self:
        keys = [w.signal for w in self.weights]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate signal in weights")
        total = sum(w.value for w in self.weights)
        if abs(total - WEIGHT_TOTAL) > WEIGHT_TOLERANCE:
            raise ValueError(f"weights must sum to 100, got {total:.3f}")
        return self

    def weight_map(self) -> dict[SignalKey, float]:
        return {w.signal: w.value for w in self.weights}


# ---------------------------------------------------------------- group D


class FounderPreferences(_Model):
    require_technical_cofounder: bool = False
    repeat_founder: RepeatFounderPref = RepeatFounderPref.ANY
    min_domain_years: int = Field(default=0, ge=0, le=40)
    require_prior_employer_hypergrowth: bool = False
    prior_employer_growth_multiple: float = Field(default=2.0, ge=1)
    require_cofounder_overlap: bool = False
    field_origins: dict[str, Origin] = Field(default_factory=dict)


# ---------------------------------------------------------------- decision


class DecisionThresholds(_Model):
    meet_min_score: float = Field(default=75, ge=0, le=100)
    meet_min_confidence: float = Field(default=0.7, ge=0, le=1)
    watch_min_score: float = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.watch_min_score > self.meet_min_score:
            raise ValueError("watch_min_score must be <= meet_min_score")
        return self


# ---------------------------------------------------------------- group E


class RunControls(_Model):
    top_n: int = Field(default=10, ge=1, le=50)
    credit_budget: float = Field(default=130, gt=0)
    profiling_budget: float = Field(default=30, ge=0)
    llm_budget_inr: float | None = Field(default=None, ge=0)
    time_limit_s: int = Field(default=600, gt=0)
    as_of: date | None = Field(
        default=None, description="None = today (live); past date = replay."
    )
    post_window_months: int = Field(default=12, ge=1, le=60)
    portfolio_sample_max: int = Field(default=25, ge=1, le=200)
    max_staleness_days: int = Field(default=90, ge=1)
    show_cannot_verify: bool = True
    save_profile: bool = False
    never_pad: bool = Field(
        default=True, description="Return fewer than top_n rather than pad."
    )

    @field_validator("as_of")
    @classmethod
    def _not_future(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("as_of cannot be in the future")
        return v

    @property
    def is_replay(self) -> bool:
        return self.as_of is not None and self.as_of < date.today()


# ---------------------------------------------------------------- root


class ScoutRequest(_Model):
    """Full parameter set for one scout run.

    Two entry paths, both supported:
      * profile path:  `investor` set; thesis/weights get inferred.
      * thesis path:   `thesis_text` and/or a filled `thesis` (client
                       requests, hidden tests).
    """

    schema_version: str = SCHEMA_VERSION
    client_id: str = Field(
        default="default", description="Separates state/config per client."
    )
    investor: InvestorIdentity | None = None
    resolved: ResolvedIdentity | None = None
    profile: InvestorProfile | None = None
    thesis_text: str | None = Field(default=None, max_length=2000)
    thesis: Thesis = Field(default_factory=Thesis)
    signals: SignalThresholds = Field(default_factory=SignalThresholds)
    ranking: Ranking
    founders: FounderPreferences = Field(default_factory=FounderPreferences)
    decision: DecisionThresholds = Field(default_factory=DecisionThresholds)
    run: RunControls = Field(default_factory=RunControls)

    @model_validator(mode="after")
    def _has_entry_point(self) -> Self:
        thesis_given = bool(
            self.thesis.industries
            or self.thesis.subsectors
            or self.thesis.keywords
        )
        if self.investor is None and not self.thesis_text and not thesis_given:
            raise ValueError(
                "provide `investor` (profile path) or `thesis_text` / "
                "thesis industries/subsectors/keywords (thesis path)"
            )
        return self
