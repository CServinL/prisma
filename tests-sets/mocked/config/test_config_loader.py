"""
Tests for OUR ConfigLoader logic: loading, YAML merging, dot-notation get(),
and has_zotero_credentials() business rule.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from prisma.utils.config import ConfigLoader, PrismaConfig


CONFIG_YAML = """
llm:
  model: "test-model"
  host: "localhost:11434"

search:
  default_limit: 5
  sources: ["arxiv"]

sources:
  zotero:
    enabled: true
    api_key: "aabbccddeeff00112233445566"
    library_id: "12345"
"""


def test_defaults_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISMA_CONFIG", str(tmp_path / "nonexistent.yaml"))
    loader = ConfigLoader()
    assert loader.config.llm.provider == "ollama"
    assert loader.config.llm.model == "llama3.1:8b"
    assert loader.config.search.default_limit == 10


def test_yaml_merged_into_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG_YAML)
    monkeypatch.setenv("PRISMA_CONFIG", str(cfg))

    loader = ConfigLoader()
    assert loader.config.llm.model == "test-model"
    assert loader.config.llm.host == "localhost:11434"
    assert loader.config.search.default_limit == 5
    assert loader.config.llm.provider == "ollama"  # default preserved
    assert loader.config.sources.zotero.enabled is True


def test_get_dot_notation_existing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISMA_CONFIG", str(tmp_path / "nonexistent.yaml"))
    loader = ConfigLoader()
    assert loader.get("llm.provider") == "ollama"


def test_get_dot_notation_missing_key_returns_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISMA_CONFIG", str(tmp_path / "nonexistent.yaml"))
    loader = ConfigLoader()
    assert loader.get("nonexistent.key", "fallback") == "fallback"


def test_has_zotero_credentials_false_by_default(tmp_path, monkeypatch):
    # Write a real but credential-free config so we don't fall through to ~/.config/prisma/
    cfg = tmp_path / "empty.yaml"
    cfg.write_text("{}")
    monkeypatch.setenv("PRISMA_CONFIG", str(cfg))
    loader = ConfigLoader()
    assert loader.has_zotero_credentials() is False


def test_has_zotero_credentials_true_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISMA_CONFIG", str(tmp_path / "nonexistent.yaml"))
    loader = ConfigLoader()
    loader.config.sources.zotero.enabled = True
    loader.config.sources.zotero.api_key = "aabbccddeeff00112233445566"
    loader.config.sources.zotero.library_id = "12345"
    assert loader.has_zotero_credentials() is True


def test_local_api_url_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISMA_CONFIG", str(tmp_path / "nonexistent.yaml"))
    loader = ConfigLoader()
    assert loader.config.sources.zotero.local_api_url == "http://localhost:23119"
