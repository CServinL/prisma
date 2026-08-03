"""Unit tests for app.py's POST /review route -- specifically that
include_authors (ADR-less, roadmap Phase 5) actually reaches
PrismaCoordinator.run_review()'s config dict. Previously this field
existed on ReviewRequest's sibling `include_authors` review_config key but
was hardcoded to False -- nothing threaded the request field through.
"""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from prisma.server.app import app
from prisma.storage.models.agent_models import CoordinatorResult, PipelineMetadata

client = TestClient(app, client=("127.0.0.1", 12345))


def _coordinator_result() -> CoordinatorResult:
    return CoordinatorResult(
        success=True, papers_analyzed=0, authors_found=0, output_file="out.md",
        total_duration=0.0, pipeline_metadata=PipelineMetadata(),
    )


def test_review_route_threads_include_authors_true_into_review_config(monkeypatch):
    from prisma.server import app as app_module

    coordinator = MagicMock()
    coordinator.run_review.return_value = _coordinator_result()
    monkeypatch.setattr(app_module, "PrismaCoordinator", lambda: coordinator)

    r = client.post("/review", json={"topic": "quantum computing", "include_authors": True})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # /review runs the actual work in a background ThreadPoolExecutor --
    # poll the job status until it's no longer pending rather than
    # asserting on the mock immediately after the request returns.
    import time
    for _ in range(50):
        status = client.get(f"/review/{job_id}").json()
        if status["status"] != "pending":
            break
        time.sleep(0.05)

    assert coordinator.run_review.call_args[0][0]["include_authors"] is True


def test_review_route_include_authors_defaults_to_false(monkeypatch):
    from prisma.server import app as app_module

    coordinator = MagicMock()
    coordinator.run_review.return_value = _coordinator_result()
    monkeypatch.setattr(app_module, "PrismaCoordinator", lambda: coordinator)

    r = client.post("/review", json={"topic": "quantum computing"})
    job_id = r.json()["job_id"]

    import time
    for _ in range(50):
        status = client.get(f"/review/{job_id}").json()
        if status["status"] != "pending":
            break
        time.sleep(0.05)

    assert coordinator.run_review.call_args[0][0]["include_authors"] is False
