"""
e2e: prisma review — full flow from search through analysis to output file.
"""

import os
import pytest
import yaml
from pathlib import Path
from click.testing import CliRunner
from prisma.cli.prisma_cli import cli


@pytest.fixture(scope="module")
def e2e_config(tmp_path_factory):
    data = {
        "sources": {
            "zotero": {
                "enabled": True,
                "mode": "hybrid",
                "local_api_url": "http://localhost:23119",
                "api_key": os.environ.get("ZOTERO_API_KEY", ""),
                "library_id": os.environ.get("ZOTERO_LIBRARY_ID", ""),
                "library_type": "user",
            }
        },
        "llm": {"provider": "ollama", "model": "llama3.1:8b", "host": "localhost:11434"},
        "search": {"default_limit": 5, "sources": ["arxiv"]},
        "output": {"directory": str(tmp_path_factory.mktemp("outputs")), "format": "markdown"},
    }
    cfg = tmp_path_factory.mktemp("e2e") / "config.yaml"
    cfg.write_text(yaml.dump(data))
    return str(cfg)


@pytest.mark.e2e
def test_review_produces_output_file(e2e_config, tmp_path):
    runner = CliRunner(mix_stderr=False)
    out = str(tmp_path / "review.md")
    result = runner.invoke(
        cli,
        ["review", "mechanistic interpretability", "--output", out, "--limit", "3"],
        env={"PRISMA_CONFIG": e2e_config},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert Path(out).exists()
