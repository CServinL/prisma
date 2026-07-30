"""
Tests for StreamScheduler._tick() selection logic and run_stream_and_notify()
behavior (prisma.server.streams_routes). All external boundaries (SearchAgent,
ConfigLoader, network) are mocked.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from prisma.services.vault import VaultService
from prisma.storage.models.zotero_models import ZoteroCollection, ZoteroCreator, ZoteroItem
from prisma.storage.models.vault_models import StreamStatus, RefreshFrequency, StreamRunResult
from prisma.storage.models.agent_models import PaperMetadata, SearchResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_paper(**kwargs) -> PaperMetadata:
    defaults = dict(
        title="Test Paper",
        authors=["Smith J"],
        abstract="An abstract.",
        source="arxiv",
        url="https://arxiv.org/abs/1234.5678",
    )
    defaults.update(kwargs)
    return PaperMetadata(**defaults)


def _make_search_result(papers=None) -> SearchResult:
    return SearchResult(
        papers=papers or [],
        query="test",
        sources_used=["arxiv"],
        total_found=len(papers or []),
    )


# ── StreamScheduler._tick() ───────────────────────────────────────────────────

class TestStreamSchedulerTick:
    """Tests for which streams _tick() decides to run."""

    @pytest.fixture
    def vault(self, tmp_path):
        v = VaultService(tmp_path)
        v.ensure_dirs()
        return v

    def _make_tick(self, vault):
        """Return a StreamScheduler bound to the given vault (via a getter,
        matching the real constructor), with run_stream_and_notify mocked."""
        from prisma.server.streams_routes import StreamScheduler

        scheduler = StreamScheduler(
            get_vault=lambda: vault,
            get_zotero=lambda: MagicMock(),
            broadcast_fn=lambda *a, **kw: None,
        )
        calls = []

        def fake_run_stream_and_notify(vault_arg, zotero_arg, slug, broadcast_fn, force=False):
            calls.append(slug)
            return StreamRunResult(slug=slug, papers_found=0, papers_saved=0,
                                   sources_used=[], sources_skipped=[])

        return scheduler, calls, fake_run_stream_and_notify

    def test_skips_paused_stream(self, vault):
        vault.create_stream(title="Paused", query="q")
        vault.save_stream("paused", status="paused")

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch("prisma.server.streams_routes.run_stream_and_notify", fake_run):
            scheduler._tick()

        assert calls == []

    def test_skips_archived_stream(self, vault):
        vault.create_stream(title="Old", query="q")
        vault.save_stream("old", status="archived")

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch("prisma.server.streams_routes.run_stream_and_notify", fake_run):
            scheduler._tick()

        assert calls == []

    def test_skips_manual_frequency(self, vault):
        vault.create_stream(title="Manual", query="q", refresh_frequency="manual")

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch("prisma.server.streams_routes.run_stream_and_notify", fake_run):
            scheduler._tick()

        assert calls == []

    def test_skips_stream_not_yet_due(self, vault):
        vault.create_stream(title="Future", query="q")
        vault.save_stream("future", next_update=datetime.now() + timedelta(hours=2))

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch("prisma.server.streams_routes.run_stream_and_notify", fake_run):
            scheduler._tick()

        assert calls == []

    def test_runs_overdue_stream(self, vault):
        vault.create_stream(title="Overdue", query="q")
        vault.save_stream("overdue", next_update=datetime.now() - timedelta(hours=1))

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch("prisma.server.streams_routes.run_stream_and_notify", fake_run):
            scheduler._tick()

        assert "overdue" in calls

    def test_runs_stream_with_no_next_update(self, vault):
        vault.create_stream(title="Never Run", query="q")
        # next_update is None by default — treat as always due

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch("prisma.server.streams_routes.run_stream_and_notify", fake_run):
            scheduler._tick()

        assert "never-run" in calls

    def test_runs_only_due_streams_when_mixed(self, vault):
        vault.create_stream(title="Due", query="q")
        vault.save_stream("due", next_update=datetime.now() - timedelta(minutes=1))

        vault.create_stream(title="Not Due", query="q")
        vault.save_stream("not-due", next_update=datetime.now() + timedelta(days=3))

        vault.create_stream(title="Paused", query="q")
        vault.save_stream("paused", status="paused")

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch("prisma.server.streams_routes.run_stream_and_notify", fake_run):
            scheduler._tick()

        assert calls == ["due"]

    def test_tick_continues_after_run_stream_error(self, vault):
        vault.create_stream(title="Boom", query="q")
        vault.save_stream("boom", next_update=datetime.now() - timedelta(hours=1))

        vault.create_stream(title="Fine", query="q")
        vault.save_stream("fine", next_update=datetime.now() - timedelta(hours=1))

        calls = []

        def failing_run(vault_arg, zotero_arg, slug, broadcast_fn, force=False):
            calls.append(slug)
            if slug == "boom":
                raise RuntimeError("network error")
            return StreamRunResult(slug=slug, papers_found=0, papers_saved=0,
                                   sources_used=[], sources_skipped=[])

        scheduler, _, _ = self._make_tick(vault)
        with patch("prisma.server.streams_routes.run_stream_and_notify", failing_run):
            scheduler._tick()  # must not raise

        assert "fine" in calls


# ── run_stream_and_notify() ───────────────────────────────────────────────────

class TestRunStream:
    """Tests for run_stream_and_notify() behavior. Unlike the old _run_stream
    (which read module globals _vault/_zotero off prisma.server.app), this
    function takes vault/zotero/broadcast_fn as explicit parameters -- no
    app_mod patching needed for those three."""

    @pytest.fixture
    def vault(self, tmp_path):
        v = VaultService(tmp_path)
        v.ensure_dirs()
        return v

    @pytest.fixture
    def mock_cfg(self):
        cfg = MagicMock()
        cfg.sources = ["arxiv"]
        cfg.default_limit = 10
        return cfg

    @pytest.fixture
    def mock_zotero(self):
        z = MagicMock()
        z.is_available.return_value = True
        z.ensure_collection.return_value = ZoteroCollection(key="TESTCOLL", name="Test")
        z.get_collection_items.return_value = []
        z.search_items.return_value = []
        z.find_by_identifier.return_value = None
        z.add_paper.return_value = MagicMock(key="ITEM1", version=0, collections=[])
        return z

    def _patched_run(self, cfg, agent_mock):
        """Return patches for everything run_stream_and_notify's callee
        (stream_runner.run_stream) reaches for besides vault/zotero (now
        explicit params, not module globals)."""
        loader_mock = MagicMock()
        loader_mock.return_value.get_search_config.return_value = cfg

        agent_cls_mock = MagicMock(return_value=agent_mock)

        from prisma.storage.models.api_response_models import LLMRelevanceResult, LLMIdentityResult
        analysis_mock = MagicMock()
        analysis_mock.assess_relevance.return_value = LLMRelevanceResult(
            is_relevant=True,
            relevance_level="RELEVANT",
            confidence=0.9,
            reasoning="mock",
            semantic_score=0.9,
        )
        analysis_mock.check_identity_batch.side_effect = (
            lambda title, abstract, candidates: [
                LLMIdentityResult(are_same=False, confidence=0.9, reason="mock")
                for _ in candidates
            ]
        )
        analysis_mock.batch_relevance_check.side_effect = (
            lambda query, candidates: [True for _ in candidates]
        )
        analysis_cls_mock = MagicMock(return_value=analysis_mock)

        return (
            patch("prisma.utils.config.ConfigLoader", loader_mock),
            patch("prisma.agents.search_agent.SearchAgent", agent_cls_mock),
            patch("prisma.agents.analysis_agent.AnalysisAgent", analysis_cls_mock),
        )

    def _run(self, vault, zotero, slug, force=False):
        from prisma.server.streams_routes import run_stream_and_notify
        return run_stream_and_notify(vault, zotero, slug, lambda *a, **kw: None, force=force)

    def test_returns_not_due_when_next_update_in_future(self, vault, mock_cfg, mock_zotero):
        vault.create_stream(title="Soon", query="q")
        vault.save_stream("soon", next_update=datetime.now() + timedelta(hours=1))

        agent = MagicMock()
        p1, p2, p3 = self._patched_run(mock_cfg, agent)
        with p1, p2, p3:
            result = self._run(vault, mock_zotero, "soon", force=False)

        assert result.papers_found == 0
        assert any("not due" in e for e in result.errors)
        agent.preflight.assert_not_called()

    def test_force_bypasses_not_due(self, vault, mock_cfg, mock_zotero):
        vault.create_stream(title="Soon", query="q")
        vault.save_stream("soon", next_update=datetime.now() + timedelta(hours=1))

        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result()

        p1, p2, p3 = self._patched_run(mock_cfg, agent)
        with p1, p2, p3:
            self._run(vault, mock_zotero, "soon", force=True)

        agent.preflight.assert_called_once()

    def test_raises_404_for_missing_stream(self, vault, mock_cfg, mock_zotero):
        from fastapi import HTTPException
        agent = MagicMock()
        p1, p2, p3 = self._patched_run(mock_cfg, agent)
        with p1, p2, p3:
            with pytest.raises(HTTPException) as exc_info:
                self._run(vault, mock_zotero, "does-not-exist")
        assert exc_info.value.status_code == 404

    def test_returns_early_when_all_sources_fail_preflight(self, vault, mock_cfg, mock_zotero):
        vault.create_stream(title="Net", query="q")

        agent = MagicMock()
        agent.preflight.return_value = []  # all fail

        p1, p2, p3 = self._patched_run(mock_cfg, agent)
        with p1, p2, p3:
            result = self._run(vault, mock_zotero, "net", force=True)

        assert result.papers_found == 0
        assert result.papers_saved == 0
        assert any("preflight" in e for e in result.errors)
        agent.search.assert_not_called()

    def test_saves_new_papers_to_zotero(self, vault, mock_cfg):
        vault.create_stream(title="AI", query="artificial intelligence")

        # Title shares stems with the query so it clears the stem pre-filter —
        # a title unrelated to the query (e.g. "Attention Is All You Need") is
        # exactly what that filter is meant to screen out before the LLM call.
        paper = _make_paper(title="Artificial Intelligence and Attention Mechanisms", authors=["Vaswani A"])
        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result(papers=[paper])

        zotero = MagicMock()
        zotero.is_available.return_value = True
        zotero.ensure_collection.return_value = ZoteroCollection(key="TESTCOLL", name="AI")
        zotero.get_collection_items.return_value = []
        zotero.search_items.return_value = []
        zotero.find_by_identifier.return_value = None
        zotero.add_paper.return_value = MagicMock(key="ITEM1", version=0, collections=[])

        p1, p2, p3 = self._patched_run(mock_cfg, agent)
        with p1, p2, p3:
            result = self._run(vault, zotero, "ai", force=True)

        assert result.papers_found == 1
        assert result.papers_saved == 1
        zotero.ensure_collection.assert_called_once()
        zotero.add_paper.assert_called_once()
        zotero.add_item_to_collection.assert_called_once()

    def test_does_not_save_duplicate_papers(self, vault, mock_cfg):
        vault.create_stream(title="AI", query="q")

        paper = _make_paper(title="Attention Is All You Need", authors=["Vaswani A"])
        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result(papers=[paper])

        existing = ZoteroItem(
            key="EXISTING", title="Attention Is All You Need",
            item_type="preprint", creators=[ZoteroCreator(creator_type="author", name="Vaswani A")],
            date="2017", abstract_note=None, doi=None, url=None,
            publication_title=None, tags=[], collections=["TESTCOLL"],
        )
        zotero = MagicMock()
        zotero.is_available.return_value = True
        zotero.ensure_collection.return_value = ZoteroCollection(key="TESTCOLL", name="AI")
        zotero.get_collection_items.return_value = [existing]
        zotero.search_items.return_value = []

        p1, p2, p3 = self._patched_run(mock_cfg, agent)
        with p1, p2, p3:
            result = self._run(vault, zotero, "ai", force=True)

        assert result.papers_saved == 0
        zotero.add_paper.assert_not_called()

    def test_updates_stream_metadata_after_run(self, vault, mock_cfg, mock_zotero):
        vault.create_stream(title="Meta", query="q", refresh_frequency="weekly")

        paper = _make_paper(title="A Paper", authors=["Doe J"])
        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result(papers=[paper])

        p1, p2, p3 = self._patched_run(mock_cfg, agent)
        with p1, p2, p3:
            self._run(vault, mock_zotero, "meta", force=True)

        updated = vault.get_stream("meta")
        assert updated.total_papers == 1
        assert updated.last_updated is not None
        assert updated.next_update is not None
        assert updated.next_update > datetime.now()

    def test_reports_skipped_sources(self, vault, mock_cfg, mock_zotero):
        mock_cfg.sources = ["arxiv", "semanticscholar"]
        vault.create_stream(title="Sources", query="q")

        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]  # semanticscholar fails preflight
        agent.search.return_value = _make_search_result()

        p1, p2, p3 = self._patched_run(mock_cfg, agent)
        with p1, p2, p3:
            result = self._run(vault, mock_zotero, "sources", force=True)

        assert "semanticscholar" in result.sources_skipped
        assert "arxiv" in result.sources_used
