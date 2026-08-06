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

from prisma.agents.session_orchestrator import SessionOrchestrator
from prisma.schema_gov import ContentFormat, RichContent
from prisma.services.chat_llm import ChatLLM
from prisma.services.chat_tools import FOOTNOTES_LINE_RE, TOOL_CALL_RE, TOOLS, ChatToolbox
from prisma.storage.models.vault_models import (
    ChatRole, CitedClaimNode, ClaimNode, InferenceNode, Note, RecallRef, ToolCallNode, TurnNode,
)

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


def _claim_from_raw(item: dict, claim_texts: dict[int, str]) -> ClaimNode | None:
    """One FOOTNOTES_JSON self-reported entry -> a CitedClaimNode or
    InferenceNode, keyed off `relation` (the self-report has no `kind`
    field -- the model was never taught that vocabulary, only `relation`,
    see system_prompt_footnote_section())."""
    try:
        index = int(item["index"])
        relation = item["relation"]
    except (KeyError, TypeError, ValueError):
        return None
    claim_text = item.get("claim_text") or claim_texts.get(index) or ""
    if relation == "ai-inference":
        return InferenceNode(index=index, claim_text=claim_text)
    try:
        return CitedClaimNode(
            index=index, claim_text=claim_text, sources=item.get("sources", []), relation=relation,
        )
    except ValidationError:
        return None


def _extract_claims(reply: str) -> tuple[str, list[ClaimNode]]:
    """ADR-017: split the model's FOOTNOTES_JSON self-report off the visible
    reply text. Defensive throughout -- an LLM self-report can be malformed
    (invalid JSON, an unknown relation value, a non-list) in ways a tool
    call marker can't be, and a bad self-report must degrade to "no
    claims," never break the turn. Only the *last* match is used, in
    case the model discusses the format itself earlier in its answer."""
    matches = list(FOOTNOTES_LINE_RE.finditer(reply))
    if not matches:
        return reply.strip(), []
    last = matches[-1]
    content = (reply[: last.start()] + reply[last.end():]).strip()
    try:
        raw_items = json.loads(last.group(1))
    except (json.JSONDecodeError, ValueError) as exc:
        _log.warning("chat claims: malformed FOOTNOTES_JSON, dropping: %s", exc)
        return content, []
    if not isinstance(raw_items, list):
        _log.warning("chat claims: FOOTNOTES_JSON was not a JSON array, dropping")
        return content, []
    claim_texts = _extract_claim_texts(content)
    claims: list[ClaimNode] = []
    for item in raw_items:
        claim = _claim_from_raw(item, claim_texts)
        if claim is None:
            _log.warning("chat claims: skipping malformed entry %r", item)
            continue
        claims.append(claim)
    return content, claims


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
        self._orchestrator = SessionOrchestrator(system_prompt, max_history_tokens)
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

    def reachable(self) -> bool:
        return self._llm.reachable()

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

    def _verify_claim(self, claim: ClaimNode) -> ClaimNode:
        """ADR-017's faithfulness_checked hook: does claim_text actually say
        what the cited source(s) say? Only meaningful for CitedClaimNode --
        InferenceNode structurally has no sources to check against, passed
        through unchanged. A missing claim_text or unresolvable source slug
        is a "couldn't check," not a "checked and failed.\""""
        if not isinstance(claim, CitedClaimNode) or not claim.sources or not claim.claim_text:
            return claim
        source_texts = [t for t in (self._toolbox.get_node_text(s) for s in claim.sources) if t]
        if not source_texts:
            return claim
        system_prompt, content = _build_faithfulness_prompt(claim.claim_text, source_texts)
        verdict = _parse_faithfulness_verdict(self.complete_once(system_prompt, content))
        return claim.model_copy(update={"faithfulness_checked": verdict})

    def respond(
        self, history: list[TurnNode], user_text: str, excerpt_notes: list[Note] | None = None,
        chat_slug: str | None = None,
    ) -> TurnNode:
        """`chat_slug` is only used to exclude this chat from cross-chat
        RECALL (`chat_tools.py`'s `_recent_other_chats`) -- `respond()` is
        otherwise chat-agnostic (all it knows about the conversation is
        `history`), so callers that don't have a slug yet (tests, one-off
        completions) can simply omit it: `RECALL` degrades to its original
        single-chat behavior, not an error."""
        messages = [{"role": "system", "content": self._orchestrator.full_system_prompt(excerpt_notes or [])}]
        for m in self._orchestrator.bounded_history(history):
            messages.append({"role": m.role.value, "content": m.content.value})
        messages.append({"role": "user", "content": user_text})

        # Built once per respond() call, not per loop iteration -- `history`
        # doesn't change during the loop, so nothing invalidates it early.
        # Lets RECALL (chat_tools.py) reach turns bounded_history() dropped
        # above, not just the current turn's own tool calls/reasoning.
        session_graph = self._orchestrator.graph_for(history)

        tool_calls: list[ToolCallNode] = []
        recalls: list[RecallRef] = []
        for _ in range(MAX_TOOL_ITERATIONS):
            # Checked before every completion call, not just the first --
            # bounded_history() caps prior history against max_history_tokens
            # (a soft session budget, deliberately larger than any one
            # backend's real ceiling, see DEFAULT_MAX_HISTORY_TOKENS/ADR-015's
            # "Resolved" section), and the Excerpt block is NEVER subject to
            # that trim at all -- neither guards the backend's actual
            # context_window. A tool result injected mid-loop can also push
            # an initially-fitting assembly over the edge. Failing fast here,
            # before ever calling the backend, beats a confusing generic
            # "couldn't reach the model" once it 400s.
            estimated = sum(_estimate_tokens(m["content"]) for m in messages)
            if estimated > self.context_window:
                return TurnNode(
                    role=ChatRole.assistant,
                    content=RichContent(format=ContentFormat.markdown, value=(
                        f"This chat's history and Excerpt exceed {self.model}'s context "
                        f"window (~{estimated} tokens estimated vs. a {self.context_window}-"
                        "token limit) -- I can't continue. Remove some pinned turns to free "
                        "up context from Excerpt buildup, or switch this chat to a model "
                        "with a bigger context window."
                    )),
                    tool_calls=tool_calls, recalls=recalls, model=self.model,
                )
            reply = self._llm.complete(messages)
            if reply is None:
                reason = self._blocked_reason()
                detail = f" — {reason}" if reason else ""
                return TurnNode(
                    role=ChatRole.assistant,
                    content=RichContent(
                        format=ContentFormat.markdown,
                        value=f"Sorry, I couldn't reach the language model just now{detail}. Please try again shortly.",
                    ),
                    tool_calls=tool_calls, recalls=recalls, model=self.model,
                )
            match = TOOL_CALL_RE.search(reply)
            if not match:
                content, claims = _extract_claims(reply)
                claims = [self._verify_claim(c) for c in claims]
                return TurnNode(
                    role=ChatRole.assistant, content=RichContent(format=ContentFormat.markdown, value=content),
                    tool_calls=tool_calls, claims=claims, recalls=recalls, model=self.model,
                )

            marker, query = match.group(1), match.group(2).strip()
            remaining_budget = max(self.context_window - estimated, 0)
            result = self._toolbox.call(
                marker, query, session_graph=session_graph, remaining_budget=remaining_budget,
                chat_slug=chat_slug,
            )
            tool_calls.append(ToolCallNode(
                tool=_TOOL_NAME_BY_MARKER[marker], args={"query": query},
                result=result.text or None, status="ok",
            ))
            if marker == "RECALL":
                # A separate record from tool_calls above (which only says
                # "RECALL ran") -- this is *which* specific earlier nodes it
                # actually surfaced, so a future turn's assembly can see what
                # was already pulled back in without re-searching. chat_slug
                # carries a cross-chat hit's source chat through (None for a
                # same-chat hit) -- dropping it here would silently discard
                # `_recall()`'s cross-chat tagging before it ever reaches the
                # persisted TurnNode.recalls.
                recalls.extend(
                    RecallRef(node_id=item["node_id"], node_kind=item["kind"], chat_slug=item.get("chat_slug"))
                    for item in result.raw
                )
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": f"Tool result:\n{result.text or '(no results found)'}",
            })

        _log.warning("chat tool loop hit MAX_TOOL_ITERATIONS=%d without a final answer", MAX_TOOL_ITERATIONS)
        return TurnNode(
            role=ChatRole.assistant,
            content=RichContent(
                format=ContentFormat.markdown,
                value="I wasn't able to reach a final answer after checking several sources — could you rephrase?",
            ),
            tool_calls=tool_calls, recalls=recalls, model=self.model,
        )

    def context_usage(self, history: list[TurnNode], excerpt_notes: list[Note] | None = None) -> tuple[int, int]:
        """(tokens_used, max_tokens) for the UI's context label — the same
        base assembly `respond()` sends (system prompt + tool section +
        Excerpt + bounded history, not counting mid-loop tool-result growth),
        estimated with the same len(s)//4 heuristic used throughout this
        codebase. max_tokens is `max_history_tokens` (the session's
        configured budget), not the backend's raw context ceiling — see
        ADR-015's "Resolved" section for why."""
        system_prompt = self._orchestrator.full_system_prompt(excerpt_notes or [])
        bounded = self._orchestrator.bounded_history(history)
        used = _estimate_tokens(system_prompt) + sum(_estimate_tokens(m.content.value) for m in bounded)
        return used, self._orchestrator.max_history_tokens
