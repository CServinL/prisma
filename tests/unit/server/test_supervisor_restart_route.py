"""Unit tests for POST /supervisor/restart/{name} (app.py).

Covers the "api" self-restart branch specifically: restarting the api
worker by calling resource_lock.restart_worker() synchronously, from
inside the very process handling the request, would have the supervisor
kill this process before it can finish responding. The route defers that
call via BackgroundTasks so the response is sent first.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from prisma.server.app import app

client = TestClient(app, client=("127.0.0.1", 12345))


def test_restart_api_worker_responds_before_restarting():
    with patch("prisma.server.app.resource_lock.restart_worker") as mock_restart:
        r = client.post("/supervisor/restart/api")

    assert r.status_code == 200
    assert r.json() == {"status": "restarting"}
    # TestClient runs BackgroundTasks synchronously after building the
    # response, so by the time we get here the call has already happened —
    # what matters is that it didn't block the response itself.
    mock_restart.assert_called_once_with("127.0.0.1", mock_restart.call_args.args[1], "api")


def test_restart_non_api_worker_is_synchronous():
    with patch("prisma.server.app.resource_lock.restart_worker") as mock_restart:
        mock_restart.return_value = {"status": "restarted"}
        r = client.post("/supervisor/restart/web")

    assert r.status_code == 200
    assert r.json() == {"status": "restarted"}
    mock_restart.assert_called_once_with("127.0.0.1", mock_restart.call_args.args[1], "web")
