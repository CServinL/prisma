"""
e2e: literature review via the API — full flow from search through analysis
to output file. `prisma review` (CLI) was removed 2026-07-27 in favor of
POST /review; this test moved with it, matching test_stream_flow.py's
already-established pattern of exercising the real app directly via
TestClient against the host's real ~/.config/prisma/config.toml, rather
than invoking the CLI or building an isolated fixture config.
"""

import os
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from prisma.server.app import app
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc


@pytest.mark.e2e
def test_review_produces_output_file(client):
    resp = client.post("/review", json={"topic": "mechanistic interpretability", "limit": 3})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    for _ in range(60):
        status = client.get(f"/review/{job_id}").json()
        if status["status"] in ("done", "error"):
            break
        time.sleep(2)
    else:
        pytest.fail(f"review job {job_id} did not finish in time")

    assert status["status"] == "done", status.get("errors")
    assert os.path.exists(status["output_file"])
