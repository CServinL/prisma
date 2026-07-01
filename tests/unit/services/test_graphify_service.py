"""Unit tests for GraphifyIndexer graceful-shutdown behavior."""

from unittest.mock import MagicMock

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
