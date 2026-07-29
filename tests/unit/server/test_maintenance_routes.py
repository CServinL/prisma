"""Unit tests for GET /maintenance/deduplicate/{job_id} -- particularly the
job-store type check, since _jobs is shared with /review (whose entries are
plain dicts, not DedupJobState). Passing a review job_id to this endpoint
must 404, not raise AttributeError from job.model_dump() on a dict.
"""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from prisma.server.app import DedupJobState, _run_deduplicate, app
from prisma.storage.models.zotero_models import ZoteroCreator, ZoteroItem

client = TestClient(app, client=("127.0.0.1", 12345))


def _item(key, doi):
    return ZoteroItem(
        key=key, item_type="journalArticle", title=f"Paper {key}",
        creators=[ZoteroCreator(creator_type="author", name="A")],
        doi=doi, tags=[], collections=[],
    )


def test_unknown_job_id_returns_404():
    resp = client.get("/maintenance/deduplicate/does-not-exist")
    assert resp.status_code == 404


def test_review_job_id_returns_404_not_500(monkeypatch):
    import prisma.server.app as app_mod
    # A /review job stores a plain dict, not DedupJobState -- passing its
    # job_id to the dedup-specific status route must 404 cleanly.
    monkeypatch.setitem(app_mod._jobs, "review-job-1", {"status": "pending", "papers_analyzed": 0})
    resp = client.get("/maintenance/deduplicate/review-job-1")
    assert resp.status_code == 404


def test_real_dedup_job_returns_its_state(monkeypatch):
    import prisma.server.app as app_mod
    job = DedupJobState(status="done", dry_run=True, max_level=3, sensitivity="medium",
                         duplicates_found=2, items_deleted=0)
    monkeypatch.setitem(app_mod._jobs, "dedup-job-1", job)
    resp = client.get("/maintenance/deduplicate/dedup-job-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "dedup-job-1"
    assert body["status"] == "done"
    assert body["sensitivity"] == "medium"
    assert body["duplicates_found"] == 2


def test_run_deduplicate_does_not_count_failed_deletes_as_successful(monkeypatch):
    # Regression: delete_item() catches its own exceptions and returns
    # bool -- it never raises. items_deleted used to be incremented
    # unconditionally right after the call, so a False return (a real
    # failure) was silently counted as a successful deletion.
    import prisma.server.app as app_mod

    dup_a, dup_b = _item("A", "10.1/x"), _item("B", "10.1/x")
    mock_zotero = MagicMock()
    mock_zotero.get_all_items.return_value = [dup_a, dup_b]
    mock_zotero.delete_item.return_value = False  # simulated failure, no exception
    monkeypatch.setattr(app_mod, "_zotero", mock_zotero)

    _run_deduplicate("job-x", dry_run=False, max_level=1, sensitivity="medium")

    job = app_mod._jobs["job-x"]
    assert job.duplicates_found == 1
    assert job.items_deleted == 0
    assert job.errors and "delete_item returned False" in job.errors[0]
