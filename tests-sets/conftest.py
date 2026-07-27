"""
Root conftest for tests-sets: shared fixtures for CLI runner, temp config, and env isolation.
"""

import os
import tempfile
import pytest
from click.testing import CliRunner
from pathlib import Path
from unittest.mock import patch

from toml_write import dict_to_toml


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def write_temp_config(tmp_path):
    """Return a helper that writes a config dict to a temp TOML file and sets PRISMA_CONFIG."""
    def _write(data: dict) -> Path:
        config_file = tmp_path / "config.toml"
        config_file.write_text(dict_to_toml(data))
        return config_file
    return _write


@pytest.fixture(autouse=True)
def isolate_prisma_config(monkeypatch):
    """Ensure PRISMA_CONFIG from the environment never leaks into tests."""
    monkeypatch.delenv("PRISMA_CONFIG", raising=False)
