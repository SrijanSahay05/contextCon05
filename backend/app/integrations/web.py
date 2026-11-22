"""Crustdata web search (`/web/search/live`) and page fetch (`/web/enrich/live`)."""

from typing import Any

from app.integrations.crustdata import CrustdataBase, CrustResult
from app.models.enums import Provider, SourceKind

WebResult = CrustResult


def _pages(body: dict[str, Any], _data: Any) -> float:
    """1 credit per search page (`page: N` costs N), per the pricing page."""
    return float(body.get("page", 1))


def _urls(body: dict[str, Any], _data: Any) -> float:
    """1 credit per fetched page."""
    return float(len(body["urls"]))


class WebClient(CrustdataBase):
    """Same retry, cache, rate-limit and credit handling as `CrustdataClient`."""

    provider = Provider.web

    def search(
        self,
        query: str,
        sources: list[str] | None = None,
        site: str | None = None,
        start_date: int | None = None,
        end_date: int | None = None,
        page: int = 1,
        location: str | None = None,
    ) -> WebResult:
        """Search the web. `start_date`/`end_date` are unix seconds, as the API takes."""
        optional = {"sources": sources, "site": site, "start_date": start_date,
                    "end_date": end_date, "location": location}
        body = {"query": query, "page": page} | {k: v for k, v in optional.items() if v}
        kind = SourceKind.news if sources == ["news"] else SourceKind.web
        return self._call("POST", "/web/search/live", body, bucket="web", estimate=_pages,
                          kind=kind)

    def fetch(self, url: str, human_mode: bool = False) -> WebResult:
        """Fetch one page's HTML; `data` is the API's list with one entry."""
        body = {"urls": [url], "human_mode": human_mode}
        return self._call("POST", "/web/enrich/live", body, bucket="web", estimate=_urls,
                          kind=SourceKind.web, url=url)
