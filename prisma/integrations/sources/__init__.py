"""Registry of every discovery source.

`SearchAgent` (`prisma/agents/search_agent.py`) depends only on
`build_sources()`'s output, never on an individual concrete module --
adding a new source means adding one module here plus one entry in
`build_sources()`, with no change to `SearchAgent` itself.
"""
from __future__ import annotations

from typing import Dict, Optional

from ...utils.config import SearchConfig, SourceQuotaConfig
from .arxiv import ArxivSource
from .base import Source, SourceSearchResult
from .googlebooks import GoogleBooksSource
from .ieee_xplore import IEEEXploreSource
from .openlibrary import OpenLibrarySource
from .pubmed import PubMedSource
from .semantic_scholar import SemanticScholarSource

__all__ = ["Source", "SourceSearchResult", "build_sources"]


def _override(config: SearchConfig, name: str) -> SourceQuotaConfig:
    return config.source_overrides.get(name, SourceQuotaConfig())


def build_sources(config: Optional[SearchConfig] = None) -> Dict[str, Source]:
    """Build one instance of every discovery source, keyed by name,
    applying `config.source_overrides` on top of each module's built-in
    default. Called once by `SearchAgent.__init__()`; tests can pass a
    fresh `SearchConfig()` (or one with specific overrides) to control
    what gets built.
    """
    config = config or SearchConfig()

    arxiv_o = _override(config, "arxiv")
    ss_o = _override(config, "semanticscholar")
    ol_o = _override(config, "openlibrary")
    gb_o = _override(config, "googlebooks")
    pm_o = _override(config, "pubmed")
    ieee_o = _override(config, "ieee_xplore")

    pubmed_key = pm_o.resolve_api_key("pubmed")
    # NCBI's rate limit is deterministically 3 req/s without a key, 10 with
    # one (https://support.nlm.nih.gov/kbArticle/?pn=KA-05317) -- auto-pick
    # the right default when a key is present, still overridable explicitly.
    pubmed_rps = pm_o.requests_per_second or (10.0 if pubmed_key else 3.0)

    googlebooks_key = gb_o.resolve_api_key("googlebooks")
    # The 10,000/day cap is documented as per-key/per-project -- only claim
    # it once a key is actually configured; an explicit override still wins.
    googlebooks_daily_cap = gb_o.daily_cap or (10_000 if googlebooks_key else None)

    return {
        "arxiv": ArxivSource(
            requests_per_second=arxiv_o.requests_per_second or 1 / 3,
        ),
        "semanticscholar": SemanticScholarSource(
            requests_per_second=ss_o.requests_per_second or 1.0,
            api_key=ss_o.resolve_api_key("semanticscholar"),
        ),
        "openlibrary": OpenLibrarySource(
            requests_per_second=ol_o.requests_per_second or 3.0,
        ),
        "googlebooks": GoogleBooksSource(
            requests_per_second=gb_o.requests_per_second or 0.5,
            daily_cap=googlebooks_daily_cap,
            api_key=googlebooks_key,
        ),
        "pubmed": PubMedSource(
            requests_per_second=pubmed_rps,
            api_key=pubmed_key,
        ),
        "ieee_xplore": IEEEXploreSource(
            requests_per_second=ieee_o.requests_per_second or 0.5,
            daily_cap=ieee_o.daily_cap,
            api_key=ieee_o.resolve_api_key("ieee_xplore"),
        ),
    }
