"""Chat agentic loop — bounded, pattern-based tool calling (see ADR-014's
appendix for why pattern-based, not native function-calling, on today's
local model).

Each iteration: ask the LLM, check whether it wrote a tool-call marker line
(SEARCH_VAULT:/GRAPH_CONTEXT:), and if so call the matching tool and feed
the result back as another turn. Bounded to MAX_TOOL_ITERATIONS so a
confused model can't loop indefinitely against the shared compute pool —
same spirit as Graphify's old max_retry_depth.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Literal

from pydantic import ValidationError

from prisma.services.chat_llm import ChatLLM
from prisma.services.chat_tools import (
    FOOTNOTES_LINE_RE,
    TOOL_CALL_RE,
    TOOLS,
    ChatToolbox,
    system_prompt_footnote_section,
    system_prompt_tool_section,
)
from prisma.storage.models.vault_models import ChatMessage, ChatRole, Footnote, Note, ToolCallRecord

_log = logging.getLogger("prisma.chat_agent")

MAX_TOOL_ITERATIONS = 4

# qwen2.5:7b-32k runs at num_ctx=32768 (Qwen2.5-7B's own architectural max —
# see ADR-014). Reserve generous headroom for the system prompt + tool section
# (~500 tokens), the current user message, and up to MAX_TOOL_ITERATIONS
# rounds of tool-result injection (a single search_vault call can return a
# few thousand tokens of wrapped excerpts) — 16000 tokens for prior history
# leaves comfortably more than half the window for all of that, verified
# against the model's real ctx rather than guessed.
DEFAULT_MAX_HISTORY_TOKENS = 16000

# ADR-015's compressed-vs-verbatim threshold. A backend's context_window
# must be at least this large before verbatim mode is even considered —
# today's local qwen2.5:7b-32k (32768) stays compressed unconditionally;
# this is meant for a genuinely large-context cloud backend (the ADR's own
# example: ~1M tokens). Set well above any locally-hosted 7B-13B class
# model's real ceiling so a local model upgrade alone doesn't accidentally
# flip this.
LARGE_CONTEXT_WINDOW_THRESHOLD = 200_000

# Even once a backend clears LARGE_CONTEXT_WINDOW_THRESHOLD, pinned turns
# stay verbatim only if their raw token cost is at most this fraction of
# that window — otherwise they get compressed. 15% leaves genuine slack for
# history + tool results + the current message, not just "technically fits."
VERBATIM_MODE_MAX_RATIO = 0.15

_TOOL_NAME_BY_MARKER = {t.marker: t.name for t in TOOLS}


def _estimate_tokens(text: str) -> int:
    return len(text) // 4  # same rough char/4 heuristic used by semchunk elsewhere in this codebase


_FOOTNOTE_MARKER_RE = re.compile(r"\[\^(\d+)\]")


def _extract_claim_texts(content: str) -> dict[int, str]:
    """Best-effort span extraction: the sentence immediately preceding each
    [^N] marker in the model's rendered reply, keyed by N. Deliberately NOT
    part of the model's FOOTNOTES_JSON self-report (ADR-017 keeps that
    self-report minimal/less error-prone) -- this is derived deterministically
    from text that's already there, used as faithfulness_checked's input
    (ChatAgent._verify_footnote)."""
    claims: dict[int, str] = {}
    cursor = 0
    for m in _FOOTNOTE_MARKER_RE.finditer(content):
        preceding = content[cursor:m.start()].strip()
        sentences = re.split(r"(?<=[.!?])\s+", preceding)
        claims[int(m.group(1))] = (sentences[-1] if sentences else preceding).strip()
        cursor = m.end()
    return claims


def _extract_footnotes(reply: str) -> tuple[str, list[Footnote]]:
    """ADR-017: split the model's FOOTNOTES_JSON self-report off the visible
    reply text. Defensive throughout -- an LLM self-report can be malformed
    (invalid JSON, an unknown relation value, a non-list) in ways a tool
    call marker can't be, and a bad self-report must degrade to "no
    footnotes," never break the turn. Only the *last* match is used, in
    case the model discusses the format itself earlier in its answer."""
    matches = list(FOOTNOTES_LINE_RE.finditer(reply))
    if not matches:
        return reply.strip(), []
    last = matches[-1]
    content = (reply[: last.start()] + reply[last.end():]).strip()
    try:
        raw_items = json.loads(last.group(1))
    except (json.JSONDecodeError, ValueError) as exc:
        _log.warning("chat footnotes: malformed FOOTNOTES_JSON, dropping: %s", exc)
        return content, []
    if not isinstance(raw_items, list):
        _log.warning("chat footnotes: FOOTNOTES_JSON was not a JSON array, dropping")
        return content, []
    claim_texts = _extract_claim_texts(content)
    footnotes: list[Footnote] = []
    for item in raw_items:
        try:
            fn = Footnote.model_validate(item)
        except ValidationError as exc:
            _log.warning("chat footnotes: skipping malformed entry %r: %s", item, exc)
            continue
        if fn.claim_text is None and fn.index in claim_texts:
            fn = fn.model_copy(update={"claim_text": claim_texts[fn.index]})
        footnotes.append(fn)
    return content, footnotes


# ADR-017's faithfulness_checked hook: is a sourced footnote's claim_text
# actually supported by the vault content it cites? Same "cheap prefilter,
# LLM call only when it matters" spirit as services/dedup.py's level 4→5
# cascade, just without a cheap prefilter here -- there's no NLTK-stem-style
# shortcut for entailment, so every sourced footnote gets the LLM call.
_FAITHFULNESS_SOURCE_CHARS = 3000

_FAITHFULNESS_SYSTEM_PROMPT = (
    "You are a fact-checker. You will be given a CLAIM and one or more SOURCE "
    "excerpts. Reply with exactly one word: YES if the claim is accurately "
    "supported by the source(s), NO if it is unsupported, contradicted, or "
    "not addressed by the source(s) at all."
)


def _build_faithfulness_prompt(claim_text: str, source_texts: list[str]) -> tuple[str, str]:
    joined = "\n\n---\n\n".join(t[:_FAITHFULNESS_SOURCE_CHARS] for t in source_texts)
    return _FAITHFULNESS_SYSTEM_PROMPT, f"CLAIM:\n{claim_text}\n\nSOURCE(S):\n{joined}"


def _parse_faithfulness_verdict(reply: str | None) -> bool | None:
    if reply is None:
        return None
    verdict = reply.strip().upper()
    if verdict.startswith("YES"):
        return True
    if verdict.startswith("NO"):
        return False
    return None  # unparseable -- don't guess, leave faithfulness_checked at None


class ChatAgent:
    def __init__(
        self,
        llm: ChatLLM,
        toolbox: ChatToolbox,
        system_prompt: str,
        max_history_tokens: int = DEFAULT_MAX_HISTORY_TOKENS,
        blocked_reason: Callable[[], str | None] | None = None,
    ) -> None:
        self._llm = llm
        self._toolbox = toolbox
        self._system_prompt = system_prompt
        self._max_history_tokens = max_history_tokens
        # Called only when the LLM call fails, to say *why* rather than a
        # generic "couldn't reach it" — most commonly the shared GPU pool is
        # busy with a different model (kg extraction, chroma embedding),
        # which model_affinity makes look identical to "unreachable" from
        # ChatLLM's own point of view. Optional: app.py wires this to check
        # the kg/chroma workers' own status; tests/callers that don't care
        # simply get no extra detail.
        self._blocked_reason = blocked_reason or (lambda: None)

    @property
    def model(self) -> str:
        return self._llm.model

    @property
    def provider(self) -> str:
        return self._llm.provider

    @property
    def pool(self) -> str:
        return self._llm.pool

    @property
    def context_window(self) -> int:
        return self._llm.context_window

    def excerpt_mode(self, pinned_raw_text: str) -> Literal["compressed", "verbatim"]:
        """ADR-015's mode switch. Two checks, both required for verbatim:
        (1) the backend's context window must itself be genuinely large
        (LARGE_CONTEXT_WINDOW_THRESHOLD) — a percentage-of-window check
        alone doesn't distinguish "small local model" from "large cloud
        model," since a typical single pinned turn is a small fraction of
        *any* window, including today's local 32768-token one. Without this
        first check, verbatim mode triggered almost immediately even
        locally, defeating the point (observed live: pinning one turn never
        showed a Summary at all). (2) even on a large window, the pinned
        set's raw token cost must still leave meaningful headroom
        (VERBATIM_MODE_MAX_RATIO) — a large-context backend can still be
        overwhelmed by an enormous pinned set."""
        if self.context_window < LARGE_CONTEXT_WINDOW_THRESHOLD:
            return "compressed"
        raw_tokens = _estimate_tokens(pinned_raw_text)
        return "verbatim" if raw_tokens <= self.context_window * VERBATIM_MODE_MAX_RATIO else "compressed"

    def complete_once(self, system_prompt: str, content: str) -> str | None:
        """One-shot completion, bypassing the tool loop entirely -- shared by
        Excerpt summary regeneration (ADR-015) and faithfulness_checked
        verification (ADR-017, `_verify_footnote` below), neither of which
        is a conversational turn. Returns None on the same conditions
        `complete()` does (lease denied, backend unreachable) — caller
        decides the fallback."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        return self._llm.complete(messages)

    def _verify_footnote(self, footnote: Footnote) -> Footnote:
        """ADR-017's faithfulness_checked hook: does claim_text actually say
        what the cited source(s) say? Left at None (not False) when there's
        nothing to check against -- an ai-inference footnote has no source
        by design, and a missing claim_text or unresolvable source slug is a
        "couldn't check," not a "checked and failed.\""""
        if not footnote.sources or not footnote.claim_text:
            return footnote
        source_texts = [t for t in (self._toolbox.get_node_text(s) for s in footnote.sources) if t]
        if not source_texts:
            return footnote
        system_prompt, content = _build_faithfulness_prompt(footnote.claim_text, source_texts)
        verdict = _parse_faithfulness_verdict(self.complete_once(system_prompt, content))
        return footnote.model_copy(update={"faithfulness_checked": verdict})

    def respond(
        self, history: list[ChatMessage], user_text: str, excerpt_notes: list[Note] | None = None,
    ) -> ChatMessage:
        messages = [{"role": "system", "content": self._full_system_prompt(excerpt_notes or [])}]
        for m in self._bounded_history(history):
            messages.append({"role": m.role.value, "content": m.content})
        messages.append({"role": "user", "content": user_text})

        tool_calls: list[ToolCallRecord] = []
        for _ in range(MAX_TOOL_ITERATIONS):
            reply = self._llm.complete(messages)
            if reply is None:
                reason = self._blocked_reason()
                detail = f" — {reason}" if reason else ""
                return ChatMessage(
                    role=ChatRole.assistant,
                    content=f"Sorry, I couldn't reach the language model just now{detail}. Please try again shortly.",
                    tool_calls=tool_calls,
                )
            match = TOOL_CALL_RE.search(reply)
            if not match:
                content, footnotes = _extract_footnotes(reply)
                footnotes = [self._verify_footnote(fn) for fn in footnotes]
                return ChatMessage(
                    role=ChatRole.assistant, content=content, tool_calls=tool_calls, footnotes=footnotes,
                )

            marker, query = match.group(1), match.group(2).strip()
            tool_calls.append(ToolCallRecord(tool=_TOOL_NAME_BY_MARKER[marker], args={"query": query}))
            result = self._toolbox.call(marker, query)
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": f"Tool result:\n{result.text or '(no results found)'}",
            })

        _log.warning("chat tool loop hit MAX_TOOL_ITERATIONS=%d without a final answer", MAX_TOOL_ITERATIONS)
        return ChatMessage(
            role=ChatRole.assistant,
            content="I wasn't able to reach a final answer after checking several sources — could you rephrase?",
            tool_calls=tool_calls,
        )

    def context_usage(self, history: list[ChatMessage], excerpt_notes: list[Note] | None = None) -> tuple[int, int]:
        """(tokens_used, max_tokens) for the UI's context label — the same
        assembly `respond()` sends (system prompt + tool section + Excerpt +
        bounded history), estimated with the same len(s)//4 heuristic used
        throughout this codebase. max_tokens is `max_history_tokens` (the
        session's configured budget), not the backend's raw context ceiling
        — see ADR-015's "Resolved" section for why."""
        system_prompt = self._full_system_prompt(excerpt_notes or [])
        bounded = self._bounded_history(history)
        used = _estimate_tokens(system_prompt) + sum(_estimate_tokens(m.content) for m in bounded)
        return used, self._max_history_tokens

    def _full_system_prompt(self, excerpt_notes: list[Note]) -> str:
        parts = [self._system_prompt, system_prompt_tool_section(), system_prompt_footnote_section()]
        if excerpt_notes:
            parts.append(self._excerpt_context_block(excerpt_notes))
        return "\n\n".join(parts)

    def _excerpt_context_block(self, excerpt_notes: list[Note]) -> str:
        # Deliberately NOT subject to _bounded_history's rolling truncation —
        # this is durable, user-curated ground truth for this conversation
        # (see TODO.md: "meeting notes," not the raw "meeting" transcript),
        # so it must survive even after the turns that produced it roll away.
        lines = [
            "Already established in this conversation (curated by the user "
            "— treat as settled, don't re-litigate or re-ask about these):",
        ]
        for note in excerpt_notes:
            lines.append(f"\n### {note.title}\n{note.body}")
        return "\n".join(lines)

    def _bounded_history(self, history: list[ChatMessage]) -> list[ChatMessage]:
        """Keep the most recent messages whose combined estimated token
        count fits max_history_tokens, dropping the oldest first. A very
        long-running chat degrades gracefully (older context silently drops)
        rather than eventually overflowing the model's context window."""
        kept: list[ChatMessage] = []
        used = 0
        for m in reversed(history):
            cost = _estimate_tokens(m.content)
            if used + cost > self._max_history_tokens:
                break
            kept.append(m)
            used += cost
        kept.reverse()
        return kept
