"""Consistency checks across the two places a source name has to agree:
build_sources()'s registry and SOURCE_REGISTRY (quality metadata).
(SearchConfig.validate_sources used to be a third, hand-maintained copy of
this same name list -- it now imports SOURCE_NAMES from
integrations.sources instead, so it can't drift on its own; the third
check below just confirms that wiring still holds.) A mismatch here
silently degrades a source to the ONE_STAR default quality
(get_source_quality's fallback) instead of raising -- this is exactly the
class of bug the semanticscholar/semantic_scholar naming mismatch was
(fixed 2026-07-29)."""

from prisma.integrations.sources import build_sources
from prisma.storage.models.source_quality import SOURCE_REGISTRY, SourceQuality, get_source_quality
from prisma.utils.config import SearchConfig


def test_every_built_source_name_matches_its_registry_key():
    sources = build_sources()
    for key, source in sources.items():
        assert key == source.name


def test_every_built_source_has_real_quality_metadata():
    """Regression test for the semantic_scholar/semanticscholar mismatch:
    every source actually wired into SearchAgent must resolve to its real
    SOURCE_REGISTRY entry, not silently fall back to ONE_STAR."""
    sources = build_sources()
    for name in sources:
        assert name in SOURCE_REGISTRY, f"{name!r} has no SOURCE_REGISTRY entry"
        assert get_source_quality(name) != SourceQuality.ONE_STAR or SOURCE_REGISTRY[name].quality == SourceQuality.ONE_STAR


def test_every_built_source_name_is_config_valid():
    sources = build_sources()
    config = SearchConfig(sources=list(sources.keys()))  # raises if any name is rejected
    assert set(config.sources) == set(sources.keys())
