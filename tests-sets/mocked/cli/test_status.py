"""
Status command state matrix — tests OUR diagnostic decision tree, not external services.

All network boundaries mocked: requests.get (Ollama), connectivity monitor,
check_web_api_reachable (Zotero), _is_wsl, _wsl_windows_ip.
Config controlled per-case via temp files set through PRISMA_CONFIG env var.
"""

import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from prisma.cli.prisma_cli import cli

from toml_write import dict_to_toml

MINIMAL_CONFIG = {
    "sources": {
        "zotero": {
            "enabled": True,
            "api_key": "",
            "library_id": "",
        }
    },
    "llm": {"provider": "ollama", "model": "llama3.1:8b", "host": "localhost:11434"},
    "search": {"default_limit": 10, "sources": ["arxiv"]},
    "output": {"directory": "./outputs", "format": "markdown"},
}


def _run_status(tmp_path, config_data=None, wsl=False, windows_ip="10.0.0.1",
                zotero_reachable=False, ollama_ping=None, online=True, env=None):
    """Helper: write config, patch boundaries, invoke `prisma status`."""
    runner = CliRunner()

    invoke_env = {}
    if config_data is not None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(dict_to_toml(config_data))
        invoke_env["PRISMA_CONFIG"] = str(cfg)
    if env:
        invoke_env.update(env)

    def fake_requests_get(url, **kwargs):
        resp = MagicMock()
        if "/api/tags" in url:
            if ollama_ping is None:
                raise ConnectionError("unreachable")
            resp.status_code = ollama_ping
            resp.json.return_value = {"models": []}
            return resp
        raise ConnectionError("unexpected url")

    with patch("prisma.cli.prisma_cli._is_wsl", return_value=wsl), \
         patch("prisma.cli.prisma_cli._wsl_windows_ip", return_value=windows_ip), \
         patch("prisma.connectivity.monitor.is_online", online), \
         patch("prisma.integrations.zotero.client.check_web_api_reachable", return_value=zotero_reachable), \
         patch("requests.get", side_effect=fake_requests_get):
        result = runner.invoke(cli, ["status"], env=invoke_env, catch_exceptions=False)

    return result


# ── Case 1: No config file ────────────────────────────────────────────────────

def test_no_config_file(tmp_path):
    runner = CliRunner()
    missing = str(tmp_path / "nonexistent.yaml")
    with patch("prisma.cli.prisma_cli._is_wsl", return_value=False), \
         patch("prisma.connectivity.monitor.is_online", True):
        result = runner.invoke(cli, ["status"], env={"PRISMA_CONFIG": missing},
                               catch_exceptions=False)
    assert result.exit_code == 1
    assert "No config file found" in result.output
    assert "mkdir -p ~/.config/prisma" in result.output


# ── Case 2: Config present, offline ──────────────────────────────────────────

def test_offline_connectivity_warning(tmp_path):
    result = _run_status(tmp_path, MINIMAL_CONFIG, online=False,
                         zotero_reachable=True, ollama_ping=200)
    assert "offline" in result.output.lower()


# ── Case 3: Config present, online ───────────────────────────────────────────

def test_online_connectivity_ok(tmp_path):
    result = _run_status(tmp_path, MINIMAL_CONFIG, online=True,
                         zotero_reachable=True, ollama_ping=200)
    assert "Internet: reachable" in result.output


# ── Case 4: Zotero Web API reachable ─────────────────────────────────────────

def test_zotero_web_api_reachable(tmp_path):
    cfg = dict(MINIMAL_CONFIG)
    cfg["sources"] = {
        "zotero": {
            "enabled": True,
            "api_key": "aabbccddeeff00112233445566778899aabb",
            "library_id": "18078141",
        }
    }
    result = _run_status(tmp_path, cfg, zotero_reachable=True, ollama_ping=200)
    assert "Reachable" in result.output


# ── Case 5: Zotero Web API unreachable ───────────────────────────────────────

def test_zotero_web_api_unreachable(tmp_path):
    cfg = dict(MINIMAL_CONFIG)
    cfg["sources"] = {
        "zotero": {
            "enabled": True,
            "api_key": "aabbccddeeff00112233445566778899aabb",
            "library_id": "18078141",
        }
    }
    result = _run_status(tmp_path, cfg, zotero_reachable=False, ollama_ping=200)
    assert result.exit_code == 1
    assert "Unreachable" in result.output


# ── Case 6: Missing api_key and library_id ───────────────────────────────────

def test_missing_web_api_creds(tmp_path):
    result = _run_status(tmp_path, MINIMAL_CONFIG, ollama_ping=200)
    assert "missing" in result.output.lower() or "api_key" in result.output
    assert "zotero.org" in result.output


# ── Case 7: Full credentials ──────────────────────────────────────────────────

def test_full_creds(tmp_path):
    cfg = dict(MINIMAL_CONFIG)
    cfg["sources"] = {
        "zotero": {
            "enabled": True,
            "api_key": "aabbccddeeff00112233445566778899aabb",
            "library_id": "18078141",
        }
    }
    result = _run_status(tmp_path, cfg, zotero_reachable=True, ollama_ping=200)
    assert "18078141" in result.output
    assert result.exit_code == 0


# ── Case 8: Ollama reachable ──────────────────────────────────────────────────

def test_ollama_reachable(tmp_path):
    cfg = dict(MINIMAL_CONFIG)
    cfg["sources"] = {
        "zotero": {
            "enabled": True,
            "api_key": "aabbccddeeff00112233445566778899aabb",
            "library_id": "18078141",
        }
    }
    result = _run_status(tmp_path, cfg, zotero_reachable=True, ollama_ping=200)
    assert "Ollama: connected" in result.output


# ── Case 9: Ollama unreachable in WSL ─────────────────────────────────────────

def test_ollama_unreachable_wsl(tmp_path):
    cfg = dict(MINIMAL_CONFIG)
    cfg["sources"] = {
        "zotero": {
            "enabled": True,
            "api_key": "aabbccddeeff00112233445566778899aabb",
            "library_id": "18078141",
        }
    }
    result = _run_status(tmp_path, cfg, wsl=True, windows_ip="10.0.0.1",
                         zotero_reachable=True, ollama_ping=None)
    assert result.exit_code == 1
    assert "OLLAMA_HOST" in result.output
    assert "10.0.0.1" in result.output


# ── Case 10: Ollama unreachable, non-WSL ──────────────────────────────────────

def test_ollama_unreachable_non_wsl(tmp_path):
    cfg = dict(MINIMAL_CONFIG)
    cfg["sources"] = {
        "zotero": {
            "enabled": True,
            "api_key": "aabbccddeeff00112233445566778899aabb",
            "library_id": "18078141",
        }
    }
    result = _run_status(tmp_path, cfg, wsl=False, zotero_reachable=True, ollama_ping=None)
    assert result.exit_code == 1
    assert "OLLAMA_HOST" not in result.output
    assert "cannot connect" in result.output


# ── Case 11: All green ────────────────────────────────────────────────────────

def test_all_green(tmp_path):
    cfg = dict(MINIMAL_CONFIG)
    cfg["sources"] = {
        "zotero": {
            "enabled": True,
            "api_key": "aabbccddeeff00112233445566778899aabb",
            "library_id": "18078141",
        }
    }
    result = _run_status(tmp_path, cfg, zotero_reachable=True, ollama_ping=200)
    assert result.exit_code == 0
    assert "Prisma is ready" in result.output
