"""Unit tests for ChatLLM (ADR-014: openai SDK, multi-base_url)."""
from unittest.mock import MagicMock, patch

import pytest

from prisma.services.chat_llm import ChatLLM
from prisma.utils.config import ChatConfig, LLMConfig


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


def test_reachable_false_when_port_unreachable():
    # Port 1 is privileged/never listening in any test environment -- a
    # real connection-refused case.
    llm = ChatLLM(ChatConfig(provider="ollama", base_url="http://127.0.0.1:1/v1"))
    assert llm.reachable(timeout=1.0) is False


def test_reachable_true_when_port_is_open():
    import socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        llm = ChatLLM(ChatConfig(provider="llama_cpp", base_url=f"http://127.0.0.1:{port}/v1"))
        assert llm.reachable(timeout=1.0) is True
    finally:
        server.close()


def test_resolve_api_key_defaults_to_placeholder_for_ollama():
    llm = _llm(provider="ollama")
    assert llm._resolve_api_key() == "ollama"


def test_resolve_api_key_reads_named_env_var(monkeypatch):
    monkeypatch.setenv("MY_TEST_KEY", "sk-real-key")
    llm = _llm(provider="openrouter", api_key_env="MY_TEST_KEY")
    assert llm._resolve_api_key() == "sk-real-key"


def test_construction_does_not_raise_when_env_var_missing(monkeypatch):
    # A missing api_key_env is a config problem for complete() to degrade
    # on, not a reason to take the whole process down at construction time.
    monkeypatch.delenv("MISSING_TEST_KEY", raising=False)
    llm = _llm(provider="openrouter", api_key_env="MISSING_TEST_KEY")
    assert llm.config_error is not None
    assert "MISSING_TEST_KEY" in llm.config_error


def test_complete_returns_none_when_env_var_missing(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_KEY", raising=False)
    llm = _llm(provider="openrouter", api_key_env="MISSING_TEST_KEY")
    with patch.object(llm._client.chat.completions, "create") as mock_create:
        result = llm.complete([{"role": "user", "content": "hi"}])
    assert result is None
    mock_create.assert_not_called()


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


def test_complete_returns_none_when_response_has_no_choices():
    # A cloud provider can return HTTP 200 with empty choices instead of
    # raising an APIError -- not caught by the try/except around .create().
    llm = _llm()
    mock_resp = MagicMock()
    mock_resp.choices = []
    mock_resp.model_dump_json.return_value = "{}"
    with patch("prisma.services.chat_llm.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.chat_llm.resource_lock.release"), \
         patch.object(llm._client.chat.completions, "create", return_value=mock_resp):
        result = llm.complete([{"role": "user", "content": "hi"}])
    assert result is None


def test_complete_uses_config_max_tokens_by_default():
    llm = _llm(max_tokens=2000)
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    with patch("prisma.services.chat_llm.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.chat_llm.resource_lock.release"), \
         patch.object(llm._client.chat.completions, "create", return_value=mock_resp) as mock_create:
        llm.complete([{"role": "user", "content": "hi"}])
    assert mock_create.call_args.kwargs["max_tokens"] == 2000
    assert "timeout" not in mock_create.call_args.kwargs


def test_complete_per_call_max_tokens_and_timeout_override_config():
    # AnalysisAgent needs a short cap for a yes/no prompt and a long one for
    # a full summary, from the same ChatLLM instance -- confirm overrides
    # actually reach the underlying client call.
    llm = _llm(max_tokens=2000)
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    with patch("prisma.services.chat_llm.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.chat_llm.resource_lock.release"), \
         patch.object(llm._client.chat.completions, "create", return_value=mock_resp) as mock_create:
        llm.complete([{"role": "user", "content": "hi"}], max_tokens=42, timeout=7)
    assert mock_create.call_args.kwargs["max_tokens"] == 42
    assert mock_create.call_args.kwargs["timeout"] == 7


def test_default_priority_is_interactive():
    # Preserves chat's original behavior — a live chat request must never
    # queue behind bulk background work.
    assert _llm()._priority == "interactive"


def test_explicit_priority_is_honored_in_lease():
    llm = ChatLLM(ChatConfig(), ollama_host="localhost:11434", priority="background")
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    with patch("prisma.services.chat_llm.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")) as mock_acquire, \
         patch("prisma.services.chat_llm.resource_lock.release"), \
         patch("prisma.services.chat_llm.resource_lock.backoff.retry_with_backoff",
               side_effect=lambda attempt, is_success, **kw: attempt()), \
         patch.object(llm._client.chat.completions, "create", return_value=mock_resp):
        llm.complete([{"role": "user", "content": "hi"}])
    assert mock_acquire.call_args.kwargs["priority"] == "background"


class TestFromLlmConfig:
    def test_adapts_fields_and_defaults_priority_to_background(self):
        llm_config = LLMConfig(provider="ollama", model="qwen2.5:7b-32k", host="localhost:11434")
        llm = ChatLLM.from_llm_config(llm_config)
        assert llm._config.provider == "ollama"
        assert llm._config.model == "qwen2.5:7b-32k"
        assert llm._priority == "background"
        assert llm._resolve_base_url() == "http://localhost:11434/v1"

    def test_pool_passed_through_when_set(self):
        llm_config = LLMConfig(provider="openrouter", model="x", pool="cloud-openrouter")
        llm = ChatLLM.from_llm_config(llm_config)
        assert llm._config.pool == "cloud-openrouter"

    def test_pool_falls_back_to_chat_config_default_when_unset(self):
        llm_config = LLMConfig(provider="ollama", model="x")
        llm = ChatLLM.from_llm_config(llm_config)
        assert llm._config.pool == ChatConfig().pool

    def test_explicit_priority_override(self):
        llm_config = LLMConfig(provider="ollama", model="x")
        llm = ChatLLM.from_llm_config(llm_config, priority="interactive")
        assert llm._priority == "interactive"
