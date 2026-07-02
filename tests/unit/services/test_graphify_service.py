"""Unit tests for GraphifyIndexer graceful-shutdown behavior."""

from unittest.mock import MagicMock, patch

import pytest

from prisma.services.graphify_service import GraphifyIndexer


@pytest.fixture
def vault(tmp_path):
    from prisma.services.vault import VaultService
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


@pytest.fixture
def indexer(vault):
    return GraphifyIndexer(vault)


def test_stop_terminates_in_flight_subprocess(indexer):
    proc = MagicMock()
    proc.poll.return_value = None  # still running
    indexer._current_proc = proc

    indexer.stop()

    proc.terminate.assert_called_once()
    proc.wait.assert_called_once()
    proc.kill.assert_not_called()


def test_stop_escalates_to_kill_if_terminate_does_not_exit(indexer):
    import subprocess

    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = subprocess.TimeoutExpired(cmd="graphify", timeout=5)
    indexer._current_proc = proc

    indexer.stop()

    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()


def test_stop_does_nothing_when_no_subprocess_running(indexer):
    indexer._current_proc = None
    indexer.stop()  # should not raise


def test_stop_skips_already_exited_subprocess(indexer):
    proc = MagicMock()
    proc.poll.return_value = 0  # already exited
    indexer._current_proc = proc

    indexer.stop()

    proc.terminate.assert_not_called()


def test_run_graphify_locked_does_not_spawn_after_stop(indexer, tmp_path):
    # Regression: stop() must never race with subprocess spawn/registration.
    # Without holding the lock across the whole check-spawn-register step,
    # stop() could read self._current_proc in the gap before it's assigned,
    # find nothing to terminate, and leave the subprocess running unmanaged.
    # Tests _run_graphify_locked directly (below the resource-lock wrapper)
    # so this stays a pure unit test with no network involved.
    indexer._stop_event.set()

    with patch("subprocess.Popen") as mock_popen:
        result = indexer._run_graphify_locked(tmp_path)

    assert result is False
    mock_popen.assert_not_called()


def test_run_graphify_skips_when_resource_lock_denies(indexer, tmp_path):
    # _run_graphify must not spawn (or even attempt to) if the supervisor
    # says no compute pool is free right now.
    with patch("prisma.services.graphify_service.resource_lock.acquire", return_value=(False, None, None)), \
         patch("prisma.services.resource_lock.backoff.retry_with_backoff", side_effect=lambda attempt, is_success, **kw: attempt()), \
         patch.object(indexer, "_run_graphify_locked") as mock_locked:
        result = indexer._run_graphify(tmp_path)

    assert result is False
    mock_locked.assert_not_called()


def test_run_graphify_releases_lease_even_if_locked_run_raises(indexer, tmp_path):
    # The lease must be released regardless of how the actual run finishes —
    # otherwise an exception here would leak a lease forever.
    with patch("prisma.services.graphify_service.resource_lock.acquire",
               return_value=(True, "default", "api-123-abcd")) as mock_acquire, \
         patch("prisma.services.graphify_service.resource_lock.release") as mock_release, \
         patch.object(indexer, "_run_graphify_locked", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            indexer._run_graphify(tmp_path)

    mock_acquire.assert_called_once()
    mock_release.assert_called_once_with(
        indexer._supervisor_host, indexer._supervisor_port, "default", "api-123-abcd",
    )
