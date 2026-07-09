"""Unit tests for prisma.services.resource_lock — the client-side helper
around the supervisor's compute-pool leases (ADR-012)."""
from unittest.mock import MagicMock, patch

import requests

from prisma.services import resource_lock


def test_default_port_reads_env_var(monkeypatch):
    monkeypatch.setenv("PRISMA_SUPERVISOR_PORT", "9999")
    assert resource_lock.default_port() == 9999


def test_default_port_falls_back_when_unset(monkeypatch):
    monkeypatch.delenv("PRISMA_SUPERVISOR_PORT", raising=False)
    assert resource_lock.default_port() == 8760


def test_default_port_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("PRISMA_SUPERVISOR_PORT", "not-a-number")
    assert resource_lock.default_port() == 8760


def test_status_returns_resources_field_on_success():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"resources": {"default": {"capacity": 1, "in_use": 1, "leases": []}}}
    with patch("prisma.services.resource_lock.requests.get", return_value=mock_resp):
        result = resource_lock.status("127.0.0.1", 8760)

    assert result == {"default": {"capacity": 1, "in_use": 1, "leases": []}}


def test_status_returns_empty_dict_when_unreachable():
    with patch("prisma.services.resource_lock.requests.get", side_effect=requests.ConnectionError("down")):
        result = resource_lock.status("127.0.0.1", 8760)

    assert result == {}


def test_process_status_returns_worker_and_system_fields():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "api": {"pid": 1, "alive": True, "restart_count": 0, "memory_mb": 42.0},
        "kg": {"pid": 2, "alive": True, "restart_count": 0, "memory_mb": 88.5},
        "resources": {"default": {"capacity": 1, "in_use": 0, "leases": []}},
        "system": {"cpu_count": 8, "memory_total_mb": 16000.0, "memory_available_mb": 8000.0},
    }
    with patch("prisma.services.resource_lock.requests.get", return_value=mock_resp):
        result = resource_lock.process_status("127.0.0.1", 8760)

    assert "resources" not in result
    assert result["api"]["memory_mb"] == 42.0
    assert result["kg"]["memory_mb"] == 88.5
    assert result["system"]["cpu_count"] == 8


def test_process_status_returns_empty_dict_when_unreachable():
    with patch("prisma.services.resource_lock.requests.get", side_effect=requests.ConnectionError("down")):
        result = resource_lock.process_status("127.0.0.1", 8760)

    assert result == {}


def test_restart_worker_returns_supervisor_response_on_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "restarted", "worker": "api"}
    with patch("prisma.services.resource_lock.requests.post", return_value=mock_resp) as mock_post:
        result = resource_lock.restart_worker("127.0.0.1", 8760, "api")

    mock_post.assert_called_once_with("http://127.0.0.1:8760/supervisor/restart/api", timeout=10.0)
    assert result == {"status": "restarted", "worker": "api"}


def test_restart_worker_returns_error_dict_when_unreachable():
    with patch("prisma.services.resource_lock.requests.post", side_effect=requests.ConnectionError("down")):
        result = resource_lock.restart_worker("127.0.0.1", 8760, "api")

    assert "error" in result


def test_lease_yields_true_and_releases_on_success():
    with patch("prisma.services.resource_lock.acquire", return_value=(True, "default", "req-1")) as mock_acquire, \
         patch("prisma.services.resource_lock.release") as mock_release:
        with resource_lock.lease("127.0.0.1", 8760, holder="api") as granted:
            assert granted is True

    mock_acquire.assert_called_once_with("127.0.0.1", 8760, "api", None, model=None, pool=None, priority="background")
    mock_release.assert_called_once_with("127.0.0.1", 8760, "default", "req-1")


def test_lease_yields_false_when_denied_and_releases_noop():
    with patch("prisma.services.resource_lock.acquire", return_value=(False, None, None)), \
         patch("prisma.services.resource_lock.release") as mock_release, \
         patch("prisma.services.backoff.time.sleep"):
        with resource_lock.lease("127.0.0.1", 8760, holder="api", max_wait=0.01) as granted:
            assert granted is False

    # release() is still called (harmless no-op since resource/request_id are None)
    mock_release.assert_called_once_with("127.0.0.1", 8760, None, None)


def test_lease_retries_a_denied_acquire_before_giving_up():
    responses = iter([(False, None, None), (False, None, None), (True, "default", "req-2")])
    with patch("prisma.services.resource_lock.acquire", side_effect=lambda *a, **kw: next(responses)) as mock_acquire, \
         patch("prisma.services.resource_lock.release") as mock_release, \
         patch("prisma.services.backoff.time.sleep"):
        with resource_lock.lease("127.0.0.1", 8760, holder="api") as granted:
            assert granted is True

    assert mock_acquire.call_count == 3
    mock_release.assert_called_once_with("127.0.0.1", 8760, "default", "req-2")


def test_lease_gives_up_after_max_wait_elapses():
    with patch("prisma.services.resource_lock.acquire", return_value=(False, None, None)) as mock_acquire, \
         patch("prisma.services.resource_lock.release"), \
         patch("prisma.services.backoff.time.sleep"):
        with resource_lock.lease("127.0.0.1", 8760, holder="api", max_wait=0.01) as granted:
            assert granted is False

    # denied every time — retried at least once, but stopped once max_wait elapsed
    assert mock_acquire.call_count >= 1


def test_lease_passes_model_through_to_acquire():
    with patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")) as mock_acquire, \
         patch("prisma.services.resource_lock.release"):
        with resource_lock.lease("127.0.0.1", 8760, holder="api", model="qwen2.5:7b") as granted:
            assert granted is True

    mock_acquire.assert_called_once_with("127.0.0.1", 8760, "api", None, model="qwen2.5:7b", pool=None, priority="background")


def test_lease_passes_explicit_pool_through_to_acquire():
    with patch("prisma.services.resource_lock.acquire", return_value=(True, "cloud_api", "req-1")) as mock_acquire, \
         patch("prisma.services.resource_lock.release"):
        with resource_lock.lease("127.0.0.1", 8760, holder="api", model="anthropic/claude-3.5-sonnet", pool="cloud_api") as granted:
            assert granted is True

    mock_acquire.assert_called_once_with(
        "127.0.0.1", 8760, "api", None, model="anthropic/claude-3.5-sonnet", pool="cloud_api", priority="background",
    )


def test_lease_releases_even_if_body_raises():
    with patch("prisma.services.resource_lock.acquire", return_value=(True, "default", "req-1")), \
         patch("prisma.services.resource_lock.release") as mock_release:
        try:
            with resource_lock.lease("127.0.0.1", 8760, holder="api"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

    mock_release.assert_called_once_with("127.0.0.1", 8760, "default", "req-1")
