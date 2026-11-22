"""Closed vocabularies used across the scout request."""

from enum import StrEnum


class Origin(StrEnum):
    """Who set a value: the lens preset, the profile inference, or the investor."""

    LENS_DEFAULT = "lens_default"
    INFERRED = "inferred"
    INVESTOR = "investor"


class Category(StrEnum):
    FOUNDER = "founder"
    TRACTION = "traction"
    TIMING = "timing"
    MARKET = "market"


class Lens(StrEnum):
    PRE_ROUND = "pre_round"
    MOMENTUM = "momentum"
    FOUNDER_FIRST = "founder_first"
    STRATEGIC_FIT = "strategic_fit"


class Stage(StrEnum):
    PRE_SEED = "pre_seed"
    SEED = "seed"
    SERIES_A = "series_a"
    SERIES_B_PLUS = "series_b_plus"
    NO_INSTITUTIONAL_ROUND = "no_institutional_round"
    UNKNOWN = "unknown"


class BusinessModel(StrEnum):
    B2B_SAAS = "b2b_saas"
    MARKETPLACE = "marketplace"
    TECH_ENABLED_SERVICES = "tech_enabled_services"
    HARDWARE = "hardware"
    B2C = "b2c"


class Relationship(StrEnum):
    """Why the client is looking: changes the lens and the memo framing."""

    INVESTMENT = "investment"
    PARTNER = "partner"
    ACQUISITION = "acquisition"
    COMPETITOR_WATCH = "competitor_watch"


class RepeatFounderPref(StrEnum):
    ANY = "any"
    REQUIRED = "required"
    WITH_EXIT = "with_exit"


class KillRule(StrEnum):
    """Hard overrides: a fired rule forces PASS with a reason, never a score."""

    HEADCOUNT_DROP = "headcount_drop"
    FOUNDER_EXIT = "founder_exit"
    CLAIM_MISMATCH = "claim_mismatch"


class EvidenceKind(StrEnum):
    POST = "post"
    PORTFOLIO_STAT = "portfolio_stat"
    FIELD = "field"
    WEB = "web"


class Decision(StrEnum):
    MEET = "meet"
    WATCH = "watch"
    PASS = "pass"
    CANNOT_VERIFY = "cannot_verify"


class ClaimVerdict(StrEnum):
    CONSISTENT = "consistent"
    CONTRADICTED = "contradicted"
    CANNOT_VERIFY = "cannot_verify"
    STALE = "stale"
