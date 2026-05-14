"""
Tests for the source-aware offline guard in PrismaCoordinator.run_review().

Rules under test (coordinator.py):
  - If requested sources include any internet source AND is_online is False → fail fast.
  - If requested sources are zotero-only AND is_online is False → proceed (offline ok).
  - If is_online is True → no early exit regardless of sources.
"""

import unittest
from unittest.mock import patch, MagicMock

from prisma.storage.models.agent_models import CoordinatorResult, SearchResult, AnalysisResult

from .conftest import CoordinatorTestBase


class TestOfflineGuard(CoordinatorTestBase):
    """Source-aware offline check in coordinator.run_review()."""

    def _run_offline(self, sources: list) -> CoordinatorResult:
        """Run coordinator.run_review() with is_online=False and given sources."""
        config = {
            "topic": "test topic",
            "sources": sources,
            "limit": 5,
        }
        with patch("prisma.coordinator.connectivity") as mock_conn:
            mock_conn.is_online = False
            result = self.coordinator.run_review(config)
        return result

    def _run_online(self, sources: list) -> CoordinatorResult:
        """Run coordinator.run_review() with is_online=True and given sources, search stubbed."""
        config = {
            "topic": "test topic",
            "sources": sources,
            "limit": 5,
        }
        with patch("prisma.coordinator.connectivity") as mock_conn, \
             patch.object(self.coordinator.search_agent, "search",
                          return_value=self.sample_search_result), \
             patch.object(self.coordinator.analysis_agent, "analyze",
                          return_value=self.sample_analysis_result), \
             patch("builtins.open", unittest.mock.mock_open()):
            mock_conn.is_online = True
            result = self.coordinator.run_review(config)
        return result

    # --- offline + internet sources ---

    def test_offline_arxiv_fails(self):
        result = self._run_offline(["arxiv"])
        self.assertFalse(result.success)
        self.assertTrue(
            any("offline" in e.lower() or "internet" in e.lower() for e in result.errors),
            f"Expected offline error, got: {result.errors}",
        )

    def test_offline_semanticscholar_fails(self):
        result = self._run_offline(["semanticscholar"])
        self.assertFalse(result.success)

    def test_offline_mixed_sources_fails(self):
        result = self._run_offline(["arxiv", "zotero"])
        self.assertFalse(result.success)

    def test_offline_openlibrary_fails(self):
        result = self._run_offline(["openlibrary"])
        self.assertFalse(result.success)

    def test_offline_googlebooks_fails(self):
        result = self._run_offline(["googlebooks"])
        self.assertFalse(result.success)

    # --- offline + zotero-only ---

    def test_offline_zotero_only_does_not_fail_early(self):
        """Zotero is local — should not be blocked by the internet guard."""
        config = {
            "topic": "test topic",
            "sources": ["zotero"],
            "limit": 5,
        }
        with patch("prisma.coordinator.connectivity") as mock_conn, \
             patch.object(self.coordinator.search_agent, "search",
                          return_value=self.sample_search_result), \
             patch.object(self.coordinator.analysis_agent, "analyze",
                          return_value=self.sample_analysis_result), \
             patch("builtins.open", unittest.mock.mock_open()):
            mock_conn.is_online = False
            result = self.coordinator.run_review(config)

        # Must NOT fail with the offline guard message
        offline_errors = [
            e for e in result.errors
            if "offline" in e.lower() and "internet" in e.lower()
        ]
        self.assertEqual(
            offline_errors, [],
            "Zotero-only review should not be blocked by the offline guard",
        )

    # --- online, internet sources pass through ---

    def test_online_arxiv_not_blocked(self):
        result = self._run_online(["arxiv", "semanticscholar"])
        # success depends on downstream stubs; the important thing is no offline error
        offline_errors = [
            e for e in result.errors
            if "offline" in e.lower() and "internet" in e.lower()
        ]
        self.assertEqual(offline_errors, [])


if __name__ == "__main__":
    unittest.main()
