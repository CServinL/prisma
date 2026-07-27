"""Unit tests for diff_config_sections() — the smart POST /reload's section
diffing (see docs/wiki/cli.md's reload-config entry, TODO.md's "CLI
minimization" note for the fuller investigation of which sections need this
at all).
"""

from prisma.services.config_reload import diff_config_sections
from prisma.utils.config import PrismaConfig


def test_no_changes_reports_nothing():
    a = PrismaConfig()
    b = PrismaConfig()
    assert diff_config_sections(a, b) == []


def test_vault_root_change_detected():
    a = PrismaConfig()
    b = PrismaConfig(vault_root="/custom/vault")
    assert diff_config_sections(a, b) == ["vault_root"]


def test_zotero_change_detected():
    a = PrismaConfig()
    b = PrismaConfig(sources={"zotero": {"enabled": True, "api_key": "k", "library_id": "1"}})
    assert diff_config_sections(a, b) == ["sources.zotero"]


def test_retrieval_change_detected():
    a = PrismaConfig()
    b = PrismaConfig(retrieval={"embedding_model": "other-model"})
    assert diff_config_sections(a, b) == ["retrieval"]


def test_chat_config_change_detected():
    a = PrismaConfig()
    b = PrismaConfig(chat={"model": "other-model"})
    assert diff_config_sections(a, b) == ["chat"]


def test_llm_host_change_also_reports_chat():
    # chat's ChatLLM is built with cfg.get_llm_config().host, not just
    # cfg.chat itself -- a host-only change must still trigger a chat reload.
    a = PrismaConfig()
    b = PrismaConfig(llm={"host": "other-host:11434"})
    assert diff_config_sections(a, b) == ["chat"]


def test_unrelated_sections_ignored():
    # output/search/analysis/logging/server are read fresh per-call
    # elsewhere -- changing them should never trigger any reload.
    a = PrismaConfig()
    b = PrismaConfig(
        output={"directory": "./other"},
        search={"default_limit": 99},
        analysis={"summary_length": "long"},
        logging={"level": "DEBUG"},
        server={"host": "0.0.0.0"},
    )
    assert diff_config_sections(a, b) == []


def test_multiple_changes_reported_together():
    a = PrismaConfig()
    b = PrismaConfig(vault_root="/x", chat={"model": "other-model"})
    assert diff_config_sections(a, b) == ["vault_root", "chat"]
