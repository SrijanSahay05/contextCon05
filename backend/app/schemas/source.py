from typing import Any

from pydantic import BaseModel

from app.schemas.common import EX_CITATION, Citation, examples


class SourceOut(BaseModel):
    """A raw source snapshot. Highlight `citation.locator` inside `raw` (a JSON path for
    API responses; page + quote for documents)."""

    citation: Citation
    raw: Any

    model_config = examples({
        "citation": EX_CITATION,
        "raw": {"company_name": "Ledgerline", "headcount": {"linkedin_headcount_timeseries": [
            {"date": "2026-10-01", "employee_count": 42}]}},
    })
