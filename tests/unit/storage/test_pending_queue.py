"""
Unit tests for PendingWriteQueue — conflict detection and flush behaviour.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from prisma.storage.pending_queue import PendingWriteQueue, _MAX_ATTEMPTS


def _make_queue(tmp_path: Path = None) -> PendingWriteQueue:
    """Return a queue backed by a temp file that won't touch the filesystem."""
    queue_file = tmp_path / "pending.json" if tmp_path else Path("/tmp/_test_pending.json")
    # Ensure a clean slate
    if queue_file.exists():
        queue_file.unlink()
    return PendingWriteQueue(queue_file=queue_file)


def _zotero_client(search_results=None, save_returns=None):
    client = MagicMock()
    client.search_items.return_value = search_results or []
    client.save_items.return_value = save_returns if save_returns is not None else ["KEY1"]
    client.create_collection.return_value = MagicMock(key="COLL1")
    client.add_item_to_collection.return_value = True
    return client


class TestAlreadyInZotero(unittest.TestCase):
    """Tests for PendingWriteQueue._already_in_zotero()."""

    def setUp(self):
        self.q = _make_queue()

    def _paper(self, doi="", title=""):
        return {"DOI": doi, "title": title}

    def _zotero_item(self, doi="", title=""):
        item = MagicMock()
        item.doi = doi
        item.title = title
        return item

    # --- DOI matching ---

    def test_doi_match_returns_true(self):
        item = self._zotero_item(doi="10.1000/xyz")
        client = _zotero_client(search_results=[item])
        self.assertTrue(self.q._already_in_zotero(self._paper(doi="10.1000/xyz"), client))

    def test_doi_case_insensitive(self):
        item = self._zotero_item(doi="10.1000/XYZ")
        client = _zotero_client(search_results=[item])
        self.assertTrue(self.q._already_in_zotero(self._paper(doi="10.1000/xyz"), client))

    def test_doi_no_match_returns_false(self):
        item = self._zotero_item(doi="10.9999/other")
        client = _zotero_client(search_results=[item])
        result = self.q._already_in_zotero(self._paper(doi="10.1000/xyz"), client)
        # DOI search finds results but none match → falls through to title check → no title → False
        self.assertFalse(result)

    def test_no_doi_skips_doi_check(self):
        client = _zotero_client(search_results=[])
        # No DOI — should not call search_items (it may still be called for title)
        self.q._already_in_zotero(self._paper(doi="", title=""), client)
        # search_items should not have been called at all with no doi and no title
        client.search_items.assert_not_called()

    # --- Title matching ---

    def test_title_match_returns_true(self):
        item = self._zotero_item(title="Deep Learning Fundamentals")
        client = _zotero_client(search_results=[item])
        result = self.q._already_in_zotero(self._paper(title="Deep Learning Fundamentals"), client)
        self.assertTrue(result)

    def test_title_case_insensitive(self):
        item = self._zotero_item(title="Deep Learning Fundamentals")
        client = _zotero_client(search_results=[item])
        result = self.q._already_in_zotero(self._paper(title="DEEP LEARNING FUNDAMENTALS"), client)
        self.assertTrue(result)

    def test_title_no_match_returns_false(self):
        item = self._zotero_item(title="Something Else Entirely")
        client = _zotero_client(search_results=[item])
        result = self.q._already_in_zotero(self._paper(title="Deep Learning Fundamentals"), client)
        self.assertFalse(result)

    def test_no_doi_no_title_returns_false(self):
        client = _zotero_client()
        self.assertFalse(self.q._already_in_zotero(self._paper(), client))

    # --- Error handling ---

    def test_zotero_error_falls_through_to_write(self):
        client = MagicMock()
        client.search_items.side_effect = RuntimeError("Zotero unreachable")
        # Should return False (proceed with write), not raise
        result = self.q._already_in_zotero(self._paper(doi="10.1000/xyz"), client)
        self.assertFalse(result)


class TestFlushConflictDetection(unittest.TestCase):
    """flush() drops save_paper actions where item already exists in Zotero."""

    def setUp(self):
        self.q = _make_queue()

    def test_duplicate_doi_action_dropped_not_written(self):
        self.q.enqueue("save_paper", {"DOI": "10.1000/xyz", "title": "Test Paper"})

        item = MagicMock()
        item.doi = "10.1000/xyz"
        item.title = "test paper"
        client = _zotero_client(search_results=[item])

        ok, fail = self.q.flush(client)
        self.assertEqual(ok, 1)   # counted as resolved
        self.assertEqual(fail, 0)
        client.save_items.assert_not_called()  # no write

    def test_new_paper_is_written(self):
        self.q.enqueue("save_paper", {"DOI": "10.9999/new", "title": "New Paper"})
        client = _zotero_client(search_results=[])
        ok, fail = self.q.flush(client)
        self.assertEqual(ok, 1)
        client.save_items.assert_called_once()

    def test_empty_queue_returns_zeros(self):
        client = _zotero_client()
        ok, fail = self.q.flush(client)
        self.assertEqual(ok, 0)
        self.assertEqual(fail, 0)


class TestFlushDispatch(unittest.TestCase):
    """flush() dispatches each action type correctly."""

    def setUp(self):
        self.q = _make_queue()

    def test_save_paper_dispatched(self):
        self.q.enqueue("save_paper", {"DOI": "", "title": "A Paper"})
        client = _zotero_client(search_results=[])
        self.q.flush(client)
        client.save_items.assert_called_once()

    def test_create_collection_dispatched(self):
        self.q.enqueue("create_collection", {"name": "My Collection"})
        client = _zotero_client()
        self.q.flush(client)
        client.create_collection.assert_called_once_with({"name": "My Collection"})

    def test_add_to_collection_dispatched(self):
        self.q.enqueue("add_to_collection", {"item_key": "ITEM1", "collection_key": "COLL1"})
        client = _zotero_client()
        self.q.flush(client)
        client.add_item_to_collection.assert_called_once_with("ITEM1", "COLL1")

    def test_save_returns_none_raises_and_retains_action(self):
        self.q.enqueue("save_paper", {"DOI": "", "title": "Bad Paper"})
        client = _zotero_client(search_results=[])
        client.save_items.return_value = None  # explicit None to trigger the guard
        ok, fail = self.q.flush(client)
        self.assertEqual(fail, 1)
        self.assertEqual(len(self.q), 1)  # still in queue

    def test_create_collection_returns_none_raises_and_retains(self):
        self.q.enqueue("create_collection", {"name": "Broken"})
        client = _zotero_client()
        client.create_collection.return_value = None
        ok, fail = self.q.flush(client)
        self.assertEqual(fail, 1)

    def test_unknown_action_type_is_dropped_as_failure(self):
        self.q._actions.append({
            "id": "x",
            "type": "unknown_action",
            "data": {},
            "collection_key": None,
            "attempts": 0,
            "last_error": None,
            "timestamp": "2025-01-01T00:00:00+00:00",
        })
        self.q._save()
        client = _zotero_client()
        ok, fail = self.q.flush(client)
        self.assertEqual(fail, 1)


class TestFlushMaxAttempts(unittest.TestCase):
    """Actions that exceed MAX_ATTEMPTS are dropped silently."""

    def setUp(self):
        self.q = _make_queue()

    def test_exceeded_attempts_dropped(self):
        self.q._actions.append({
            "id": "z",
            "type": "save_paper",
            "data": {"DOI": "", "title": "Old"},
            "collection_key": None,
            "attempts": _MAX_ATTEMPTS,
            "last_error": "timeout",
            "timestamp": "2025-01-01T00:00:00+00:00",
        })
        self.q._save()
        client = _zotero_client(search_results=[])
        ok, fail = self.q.flush(client)
        self.assertEqual(ok, 0)
        self.assertEqual(fail, 0)
        self.assertEqual(len(self.q), 0)
        client.save_items.assert_not_called()


class TestQueueProperties(unittest.TestCase):
    """Test pending_count, __len__, __bool__."""

    def setUp(self):
        self.q = _make_queue()

    def test_empty_queue_bool_false(self):
        self.assertFalse(bool(self.q))

    def test_non_empty_queue_bool_true(self):
        self.q.enqueue("save_paper", {"DOI": "", "title": "X"})
        self.assertTrue(bool(self.q))

    def test_len_matches_action_count(self):
        self.q.enqueue("save_paper", {"DOI": "", "title": "A"})
        self.q.enqueue("create_collection", {"name": "C"})
        self.assertEqual(len(self.q), 2)
        self.assertEqual(self.q.pending_count, 2)


if __name__ == "__main__":
    unittest.main()
