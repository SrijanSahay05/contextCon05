"""Signal registry: every rankable signal, its category, and where it comes from.

Adding a signal = one entry here. Lens base weights are derived from these
entries, so nothing else needs editing.
"""

from dataclasses import dataclass
from enum import StrEnum

from .enums import Category


class SignalKey(StrEnum):
    # founder
    REPEAT_FOUNDER = "repeat_founder"
    PRIOR_EMPLOYER_HYPERGROWTH = "prior_employer_hypergrowth"
    DOMAIN_YEARS = "domain_years"
    TECHNICAL_COFOUNDER = "technical_cofounder"
    COFOUNDER_OVERLAP = "cofounder_overlap"
    PROMOTION_VELOCITY = "promotion_velocity"
    # traction
    HEADCOUNT_GROWTH_3M = "headcount_growth_3m"
    HEADCOUNT_GROWTH_6M = "headcount_growth_6m"
    HEADCOUNT_GROWTH_12M = "headcount_growth_12m"
    GROWTH_ACCELERATION = "growth_acceleration"
    ENGINEERING_SHARE = "engineering_share"
    OPEN_JOBS_TREND = "open_jobs_trend"
    WEB_TRAFFIC_TREND = "web_traffic_trend"
    LOW_ATTRITION = "low_attrition"
    # timing & capital
    RUNWAY_PRESSURE = "runway_pressure"
    MONTHS_SINCE_LAST_ROUND = "months_since_last_round"
    RAISE_CADENCE = "raise_cadence"
    NO_INSTITUTIONAL_ROUND = "no_institutional_round"
    # market
    COMPETITIVE_DENSITY = "competitive_density"
    NEWS_MOMENTUM = "news_momentum"
    STRATEGIC_FIT = "strategic_fit"


@dataclass(frozen=True)
class SignalSpec:
    key: SignalKey
    category: Category
    label: str
    description: str
    source_fields: tuple[str, ...]
    higher_is_better: bool = True
    # relative importance inside its category (used to split lens weights)
    share: float = 1.0
    # whether profile inference may move this weight
    inferable: bool = True


SIGNALS: dict[SignalKey, SignalSpec] = {
    s.key: s
    for s in (
        SignalSpec(
            SignalKey.REPEAT_FOUNDER, Category.FOUNDER, "Repeat founder",
            "Founded a company before; outcome of the last one.",
            ("person.experience",), share=1.0,
        ),
        SignalSpec(
            SignalKey.PRIOR_EMPLOYER_HYPERGROWTH, Category.FOUNDER,
            "Prior employer hypergrowth",
            "A prior employer grew 2x+ in headcount during the founder's "
            "tenure.",
            ("person.experience", "company.headcount.timeseries"), share=1.5,
        ),
        SignalSpec(
            SignalKey.DOMAIN_YEARS, Category.FOUNDER, "Domain experience",
            "Years in the company's domain before founding.",
            ("person.experience",), share=1.2,
        ),
        SignalSpec(
            SignalKey.TECHNICAL_COFOUNDER, Category.FOUNDER,
            "Technical co-founder",
            "At least one founder held engineering roles.",
            ("company.people.founders", "person.experience"), share=1.2,
        ),
        SignalSpec(
            SignalKey.COFOUNDER_OVERLAP, Category.FOUNDER, "Co-founder overlap",
            "Co-founders worked together at a previous employer.",
            ("person.experience",), share=0.8,
        ),
        SignalSpec(
            SignalKey.PROMOTION_VELOCITY, Category.FOUNDER,
            "Promotion velocity",
            "How fast the founder was promoted in prior roles.",
            ("person.experience",), share=0.6,
        ),
        SignalSpec(
            SignalKey.HEADCOUNT_GROWTH_3M, Category.TRACTION,
            "Headcount growth (3m)",
            "Recomputed from the headcount timeseries, with a size floor.",
            ("company.headcount.timeseries",), share=0.8,
        ),
        SignalSpec(
            SignalKey.HEADCOUNT_GROWTH_6M, Category.TRACTION,
            "Headcount growth (6m)",
            "Recomputed from the timeseries, anchored to "
            "metadata.growth_calculation_date.",
            ("company.headcount.timeseries",
             "company.metadata.growth_calculation_date"),
            share=1.5,
        ),
        SignalSpec(
            SignalKey.HEADCOUNT_GROWTH_12M, Category.TRACTION,
            "Headcount growth (12m)",
            "Recomputed from the headcount timeseries.",
            ("company.headcount.timeseries",), share=0.8,
        ),
        SignalSpec(
            SignalKey.GROWTH_ACCELERATION, Category.TRACTION,
            "Growth acceleration",
            "3m growth rate vs the 12m average rate.",
            ("company.headcount.timeseries",), share=1.0,
        ),
        SignalSpec(
            SignalKey.ENGINEERING_SHARE, Category.TRACTION,
            "Engineering share",
            "Share of headcount in engineering.",
            ("company.headcount.by_function_timeseries",), share=0.6,
        ),
        SignalSpec(
            SignalKey.OPEN_JOBS_TREND, Category.TRACTION, "Open jobs trend",
            "Change in open job postings.",
            ("company.hiring.open_jobs_timeseries",), share=0.7,
        ),
        SignalSpec(
            SignalKey.WEB_TRAFFIC_TREND, Category.TRACTION,
            "Web traffic trend",
            "Change in monthly visitors.",
            ("company.web_traffic.monthly_visitors_timeseries",), share=0.6,
        ),
        SignalSpec(
            SignalKey.LOW_ATTRITION, Category.TRACTION, "Low attrition",
            "Few departures in the last 6 months relative to headcount.",
            ("company.people",), share=0.6,
        ),
        SignalSpec(
            SignalKey.RUNWAY_PRESSURE, Category.TIMING, "Runway pressure",
            "Last round / (headcount x loaded cost); shorter runway = more "
            "likely to raise soon.",
            ("company.funding.milestones", "company.headcount.total"),
            share=1.5,
        ),
        SignalSpec(
            SignalKey.MONTHS_SINCE_LAST_ROUND, Category.TIMING,
            "Months since last round",
            "Time since last_fundraise_date.",
            ("company.funding.last_fundraise_date",), share=1.2,
        ),
        SignalSpec(
            SignalKey.RAISE_CADENCE, Category.TIMING, "Raise cadence",
            "Typical gap between past rounds vs time since the last one.",
            ("company.funding.milestones",), share=0.8,
        ),
        SignalSpec(
            SignalKey.NO_INSTITUTIONAL_ROUND, Category.TIMING,
            "No institutional round yet",
            "Has not yet raised from an institutional investor.",
            ("company.funding.milestones",), share=0.5,
        ),
        SignalSpec(
            SignalKey.COMPETITIVE_DENSITY, Category.MARKET,
            "Competitive density",
            "Number of funded competitors; fewer is better.",
            ("company.competitors", "company_search"),
            higher_is_better=False, share=1.0,
        ),
        SignalSpec(
            SignalKey.NEWS_MOMENTUM, Category.MARKET, "News momentum",
            "Recent press and social mentions.",
            ("web_search", "social_posts"), share=0.7,
        ),
        SignalSpec(
            SignalKey.STRATEGIC_FIT, Category.MARKET, "Strategic fit",
            "Relevance to the client's business (e.g. a 3PL's operations), "
            "classified with a sourced reason.",
            ("company.description", "company.taxonomy"), share=1.3,
        ),
    )
}

# Inputs that must never be used as signals or fed into weight inference:
# proxies for protected traits (caste, class, gender, age, religion).
PROTECTED_INPUTS: frozenset[str] = frozenset(
    {
        "education", "college", "college_tier", "university", "school",
        "degree_institution", "age", "birth_year", "graduation_year",
        "gender", "caste", "religion", "hometown", "nationality", "photo",
        "marital_status", "surname",
    }
)


def signals_in(category: Category) -> list[SignalSpec]:
    return [s for s in SIGNALS.values() if s.category == category]
