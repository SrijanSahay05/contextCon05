"""Clients for external sources: Crustdata, Crustdata web search/fetch, and the LLM."""

from typing import Protocol


class IntegrationSettings(Protocol):
    """The settings fields the clients read; the real `Settings` satisfies this."""

    @property
    def crustdata_api_key(self) -> str | None: ...

    @property
    def crustdata_base_url(self) -> str: ...

    @property
    def anthropic_api_key(self) -> str | None: ...

    @property
    def llm_model(self) -> str: ...

    @property
    def llm_fast_model(self) -> str: ...

    @property
    def cache_max_age_hours(self) -> float: ...
