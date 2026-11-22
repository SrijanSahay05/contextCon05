from pydantic import BaseModel, Field

from app.schemas.common import examples


class AliasCandidate(BaseModel):
    """A Crustdata investor record that might be the partner's firm. `preselected` records
    are Scout's best guess; the partner ticks the ones that really are the firm."""

    permalink: str
    canonical_name: str
    example_companies: list[str]
    deal_count: int
    preselected: bool

    model_config = examples(
        {
            "permalink": "kestrel-ventures",
            "canonical_name": "Kestrel Ventures",
            "example_companies": ["Paysetu", "Kirana Cloud", "LedgerLoop"],
            "deal_count": 14,
            "preselected": True,
        },
        {
            "permalink": "kestrel-capital-partners",
            "canonical_name": "Kestrel Capital Partners",
            "example_companies": ["Agrovia"],
            "deal_count": 2,
            "preselected": False,
        },
    )


class ConfirmAliases(BaseModel):
    permalinks: list[str] = Field(min_length=1)

    model_config = examples({"permalinks": ["kestrel-ventures"]})
