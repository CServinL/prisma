"""Backend-agnostic LLM interface for the chat module (ADR-014: openai SDK,
multi-base_url — not litellm, not hand-rolled requests).

Ollama and OpenRouter are both OpenAI-API-compatible, so the same `openai`
client works for either with just a base_url/api_key change. Anthropic
would need its own adapter when that backend is actually built (see
ADR-014) — not needed yet, chat is Ollama-only today.

Every call goes through resource_lock.lease(), same as the knowledge
graph's and ChromaDB's Ollama calls — one shared arbitration point for
whatever's contending for the local GPU.
"""
from __future__ import annotations

import logging
import os

from openai import OpenAI

from prisma.services import resource_lock
from prisma.utils.config import ChatConfig

_log = logging.getLogger("prisma.chat_llm")

_RESOURCE_HOLDER = "api"  # chat runs inside the api process — matches its worker name


class ChatLLM:
    def __init__(
        self,
        chat_config: ChatConfig,
        ollama_host: str = "localhost:11434",
        supervisor_host: str = "127.0.0.1",
        supervisor_port: int | None = None,
    ) -> None:
        self._config = chat_config
        self._ollama_host = ollama_host
        self._supervisor_host = supervisor_host
        self._supervisor_port = supervisor_port if supervisor_port is not None else resource_lock.default_port()
        self._client = OpenAI(base_url=self._resolve_base_url(), api_key=self._resolve_api_key())

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
        if self._config.provider == "ollama":
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
        return "ollama"  # Ollama's OpenAI-compat endpoint ignores the key but the SDK requires a non-empty string

    def complete(self, messages: list[dict], temperature: float = 0.1) -> str | None:
        """One resource_lock-gated chat completion call. Returns None if the
        lease was denied or the call failed — callers must treat that as
        "couldn't get an answer right now," not "the model said nothing.\""""
        with resource_lock.lease(
            self._supervisor_host, self._supervisor_port,
            holder=_RESOURCE_HOLDER, model=self._config.model, pool=self._config.pool,
            priority="interactive",  # a live chat request — must never queue behind bulk background work
        ) as granted:
            if not granted:
                return None
            try:
                resp = self._client.chat.completions.create(
                    model=self._config.model,
                    messages=messages,
                    temperature=temperature,
                )
            except Exception as exc:
                _log.warning("chat completion failed: %s", exc)
                return None
        return resp.choices[0].message.content
