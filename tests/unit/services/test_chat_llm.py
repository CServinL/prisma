"""Unit tests for ChatLLM (ADR-014: openai SDK, multi-base_url)."""
from unittest.mock import MagicMock, patch

import pytest

from prisma.services.chat_llm import ChatLLM
from prisma.utils.config import ChatConfig


def _llm(**overrides) -> ChatLLM:
    cfg = ChatConfig(**overrides) if overrides else ChatConfig()
    return ChatLLM(cfg, ollama_host="localhost:11434")


def test_resolve_base_url_ollama_default():
    llm = _llm(provider="ollama")
    assert llm._resolve_base_url() == "http://localhost:11434/v1"


def test_resolve_base_url_openrouter_default():
    llm = _llm(provider="openrouter")
    assert llm._resolve_base_url() == "https://openrouter.ai/api/v1"


def test_resolve_base_url_explicit_override_wins():
    llm = _llm(provider="ollama", base_url="http://custom:9999/v1")
    assert llm._resolve_base_url() == "http://custom:9999/v1"


def test_resolve_base_url_anthropic_has_no_default_yet():
    with pytest.raises(ValueError, match="anthropic"):
        _llm(provider="anthropic")


def test_resolve_api_key_defaults_to_placeholder_for_ollama():
    llm = _llm(provider="ollama")
    assert llm._resolve_api_key() == "ollama"


def test_resolve_api_key_reads_named_env_var(monkeypatch):
    monkeypatch.setenv("MY_TEST_KEY", "sk-real-key")
    llm = _llm(provider="openrouter", api_key_env="MY_TEST_KEY")
    assert llm._resolve_api_key() == "sk-real-key"


def test_resolve_api_key_raises_when_env_var_missing(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MISSING_TEST_KEY"):
        _llm(provider="openrouter", api_key_env="MISSING_TEST_KEY")


def test_complete_returns_none_when_lease_denied():
    llm = _llm()
    with patch("prisma.services.chat_llm.resource_lock.acquire", return_value=(False, None, None)), \
         patch("prisma.services.chat_llm.resource_lock.backoff.retry_with_backoff",
               side_effect=lambda attempt, is_success, **kw: attempt()):
        result = llm.complete([{"role": "user", "content": "hi"}])
    assert result is None


def test_complete_returns_content_on_success():
    llm = _llm()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="hello there"))]
    with patch("prisma.services.chat_llm.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.chat_llm.resource_lock.release"), \
         patch.object(llm._client.chat.completions, "create", return_value=mock_resp):
        result = llm.complete([{"role": "user", "content": "hi"}])
    assert result == "hello there"


def test_complete_leases_with_interactive_priority():
    # A live chat request must never queue behind bulk background work
    # (kg extraction, chroma embedding) — see ResourceManager.acquire.
    llm = _llm()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    with patch("prisma.services.chat_llm.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")) as mock_acquire, \
         patch("prisma.services.chat_llm.resource_lock.release"), \
         patch("prisma.services.chat_llm.resource_lock.backoff.retry_with_backoff",
               side_effect=lambda attempt, is_success, **kw: attempt()), \
         patch.object(llm._client.chat.completions, "create", return_value=mock_resp):
        llm.complete([{"role": "user", "content": "hi"}])

    assert mock_acquire.call_args.kwargs["priority"] == "interactive"


def test_complete_returns_none_on_client_exception():
    llm = _llm()
    with patch("prisma.services.chat_llm.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.chat_llm.resource_lock.release"), \
         patch.object(llm._client.chat.completions, "create", side_effect=RuntimeError("boom")):
        result = llm.complete([{"role": "user", "content": "hi"}])
    assert result is None
