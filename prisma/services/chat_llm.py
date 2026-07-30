"""Backend-agnostic LLM interface for the chat module (ADR-014: openai SDK,
multi-base_url — not litellm, not hand-rolled requests).

Ollama, llama.cpp (llama-server/llama-swap), and OpenRouter are all
OpenAI-API-compatible, so the same `openai` client works for any of them with
just a base_url/api_key change. Anthropic would need its own adapter when that
backend is actually built (see ADR-014).

Every call goes through resource_lock.lease(), same as the knowledge
graph's and ChromaDB's Ollama calls — one shared arbitration point for
whatever's contending for the local GPU.
"""
from __future__ import annotations

import logging
import os

from openai import OpenAI

from prisma.services import resource_lock
from prisma.utils.config import ChatConfig, LLMConfig

_log = logging.getLogger("prisma.chat_llm")

_RESOURCE_HOLDER = "api"  # chat runs inside the api process — matches its worker name


class ChatLLM:
    def __init__(
        self,
        chat_config: ChatConfig,
        ollama_host: str = "localhost:11434",
        supervisor_host: str = "127.0.0.1",
        supervisor_port: int | None = None,
        priority: str = "interactive",
    ) -> None:
        self._config = chat_config
        self._ollama_host = ollama_host
        self._supervisor_host = supervisor_host
        self._supervisor_port = supervisor_port if supervisor_port is not None else resource_lock.default_port()
        # A live chat request must never queue behind bulk background work —
        # see resource_lock.lease's docstring. Callers doing background work
        # instead (AnalysisAgent, via from_llm_config) pass priority="background".
        self._priority = priority
        # timeout=180.0: without this, an OpenAI-SDK call has no default
        # ceiling at all — found live: this call site was the one gap the
        # kg-extraction num_predict bug didn't already cover elsewhere.
        # Per-call complete(timeout=...) overrides this for callers that need
        # tighter/looser bounds per prompt (see AnalysisAgent).
        self._client = OpenAI(
            base_url=self._resolve_base_url(), api_key=self._resolve_api_key(), timeout=180.0,
        )

    @classmethod
    def from_llm_config(
        cls,
        llm_config: LLMConfig,
        *,
        priority: str = "background",
        supervisor_host: str = "127.0.0.1",
        supervisor_port: int | None = None,
    ) -> "ChatLLM":
        """Adapts LLMConfig (KG/AnalysisAgent's config shape) into the
        ChatConfig this class actually needs. LLMConfig has no `max_tokens`
        field -- ChatConfig's own default (2000) is used, and callers that
        need tighter per-call caps pass complete(max_tokens=...). `pool`
        defaults to ChatConfig's own default ("local-ollama") when
        llm_config.pool isn't set -- callers running provider="openrouter"
        should set `llm.pool` explicitly to a dedicated pool, or risk being
        auto-routed onto a model_affinity'd local-GPU pool (see
        resource_lock.lease's docstring)."""
        kwargs = dict(
            provider=llm_config.provider,
            model=llm_config.model,
            base_url=llm_config.base_url_override,
            api_key_env=llm_config.api_key_env,
        )
        if llm_config.pool:
            kwargs["pool"] = llm_config.pool
        if llm_config.context_window is not None:
            kwargs["context_window"] = llm_config.context_window
        chat_config = ChatConfig(**kwargs)
        return cls(
            chat_config,
            ollama_host=llm_config.host,
            supervisor_host=supervisor_host,
            supervisor_port=supervisor_port,
            priority=priority,
        )

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def provider(self) -> str:
        return self._config.provider

    @property
    def pool(self) -> str:
        return self._config.pool

    @property
    def context_window(self) -> int:
        return self._config.context_window

    def _resolve_base_url(self) -> str:
        if self._config.base_url:
            return self._config.base_url
        if self._config.provider in ("ollama", "llama_cpp"):
            # Both are OpenAI-API-compatible on their /v1 path — same client,
            # just a different local backend host:port (llm.host in config).
            return f"http://{self._ollama_host}/v1"
        if self._config.provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        raise ValueError(
            f"no default base_url for provider {self._config.provider!r} — set chat.base_url explicitly"
        )

    def _resolve_api_key(self) -> str:
        if self._config.api_key_env:
            key = os.environ.get(self._config.api_key_env)
            if not key:
                raise RuntimeError(
                    f"chat.api_key_env={self._config.api_key_env!r} is set but not present in the environment"
                )
            return key
        return "ollama"  # placeholder — Ollama/llama.cpp's OpenAI-compat endpoints ignore the key, but the SDK requires a non-empty string

    def complete(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        *,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str | None:
        """One resource_lock-gated chat completion call. Returns None if the
        lease was denied or the call failed — callers must treat that as
        "couldn't get an answer right now," not "the model said nothing."

        `max_tokens`/`timeout` override this instance's config default for
        just this call — e.g. AnalysisAgent wants a short cap for a
        yes/no-style prompt and a long one for a full summary, from the
        same ChatLLM instance."""
        with resource_lock.lease(
            self._supervisor_host, self._supervisor_port,
            holder=_RESOURCE_HOLDER, model=self._config.model, pool=self._config.pool,
            priority=self._priority,
        ) as granted:
            if not granted:
                return None
            try:
                kwargs = dict(
                    model=self._config.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens if max_tokens is not None else self._config.max_tokens,
                )
                if timeout is not None:
                    kwargs["timeout"] = timeout
                resp = self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                _log.warning("chat completion failed: %s", exc)
                return None
        # Cloud providers (openrouter) bill per-token — a real, per-call
        # usage record here is what actually lets "how much are we
        # spending" be answered from logs, rather than only from
        # OpenRouter's own dashboard after the fact (found live 2026-07-25:
        # a misconfigured deployment had already granted leases and hit
        # OpenRouter for several calls before anyone noticed nothing was
        # actually working — a per-call log line would have made that
        # obvious immediately instead of needing to check OpenRouter's own
        # /api/v1/key usage counter to even suspect it).
        if resp.usage is not None:
            _log.info(
                "chat completion: provider=%s model=%s prompt_tokens=%d completion_tokens=%d total_tokens=%d",
                self._config.provider, self._config.model,
                resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.total_tokens,
            )
        return resp.choices[0].message.content
