"""Unit tests for the bounded, pattern-based chat tool loop."""
from pathlib import Path
from unittest.mock import MagicMock

from prisma.agents.chat_agent import MAX_TOOL_ITERATIONS, ChatAgent
from prisma.services.chat_tools import ToolResult
from prisma.storage.models.vault_models import ChatMessage, ChatRole, Note


def _agent(llm=None, toolbox=None, max_history_tokens=16000):
    return ChatAgent(
        llm=llm or MagicMock(),
        toolbox=toolbox or MagicMock(),
        max_history_tokens=max_history_tokens,
        system_prompt="You are a test assistant.",
    )


def test_respond_returns_direct_answer_with_no_tool_call():
    llm = MagicMock()
    llm.complete.return_value = "LLM stands for Large Language Model."
    agent = _agent(llm=llm)

    reply = agent.respond(history=[], user_text="What does LLM stand for?")

    assert reply.role == ChatRole.assistant
    assert reply.content == "LLM stands for Large Language Model."
    assert reply.tool_calls == []


def test_respond_calls_tool_then_returns_final_answer():
    llm = MagicMock()
    llm.complete.side_effect = [
        "SEARCH_VAULT: attention mechanisms",
        "Based on your notes, attention mechanisms let models weigh tokens.",
    ]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="<untrusted_source>...</untrusted_source>", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="What have I written about attention?")

    toolbox.call.assert_called_once_with("SEARCH_VAULT", "attention mechanisms")
    assert reply.content == "Based on your notes, attention mechanisms let models weigh tokens."
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].tool == "search_vault"
    assert reply.tool_calls[0].args == {"query": "attention mechanisms"}


def test_respond_returns_fallback_when_llm_unreachable():
    llm = MagicMock()
    llm.complete.return_value = None
    agent = _agent(llm=llm)

    reply = agent.respond(history=[], user_text="hello")

    assert "couldn't reach" in reply.content.lower()


def test_respond_includes_blocked_reason_when_provided():
    llm = MagicMock()
    llm.complete.return_value = None
    agent = ChatAgent(
        llm=llm,
        toolbox=MagicMock(),
        system_prompt="You are a test assistant.",
        blocked_reason=lambda: "the knowledge graph is currently indexing your vault",
    )

    reply = agent.respond(history=[], user_text="hello")

    assert "knowledge graph is currently indexing" in reply.content


def test_respond_fallback_has_no_extra_detail_when_reason_is_none():
    llm = MagicMock()
    llm.complete.return_value = None
    agent = ChatAgent(
        llm=llm, toolbox=MagicMock(), system_prompt="You are a test assistant.",
        blocked_reason=lambda: None,
    )

    reply = agent.respond(history=[], user_text="hello")

    assert reply.content == "Sorry, I couldn't reach the language model just now. Please try again shortly."
    assert reply.tool_calls == []


def test_respond_stops_after_max_tool_iterations():
    llm = MagicMock()
    llm.complete.return_value = "SEARCH_VAULT: something"  # never stops calling tools
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="some result", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="loop forever")

    assert toolbox.call.call_count == MAX_TOOL_ITERATIONS
    assert len(reply.tool_calls) == MAX_TOOL_ITERATIONS
    assert "wasn't able to reach a final answer" in reply.content


def test_respond_includes_prior_history_in_messages():
    llm = MagicMock()
    llm.complete.return_value = "sure, following up on that"
    agent = _agent(llm=llm)
    history = [
        ChatMessage(role=ChatRole.user, content="first question"),
        ChatMessage(role=ChatRole.assistant, content="first answer"),
    ]

    agent.respond(history=history, user_text="follow-up question")

    sent_messages = llm.complete.call_args[0][0]
    roles_and_content = [(m["role"], m["content"]) for m in sent_messages]
    assert ("user", "first question") in roles_and_content
    assert ("assistant", "first answer") in roles_and_content
    assert ("user", "follow-up question") in roles_and_content


def test_respond_drops_oldest_history_once_token_budget_exceeded():
    llm = MagicMock()
    llm.complete.return_value = "ok"
    # Budget for ~40 tokens (160 chars at the len//4 heuristic) — enough for
    # only the most recent message, not the oldest one.
    agent = _agent(llm=llm, max_history_tokens=40)
    history = [
        ChatMessage(role=ChatRole.user, content="x" * 200),  # ~50 tokens — too old, dropped
        ChatMessage(role=ChatRole.assistant, content="y" * 100),  # ~25 tokens — kept
    ]

    agent.respond(history=history, user_text="latest question")

    sent_messages = llm.complete.call_args[0][0]
    contents = [m["content"] for m in sent_messages]
    assert "x" * 200 not in contents
    assert "y" * 100 in contents


def test_respond_keeps_all_history_within_budget():
    llm = MagicMock()
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm, max_history_tokens=16000)
    history = [
        ChatMessage(role=ChatRole.user, content="short question"),
        ChatMessage(role=ChatRole.assistant, content="short answer"),
    ]

    agent.respond(history=history, user_text="another question")

    sent_messages = llm.complete.call_args[0][0]
    contents = [m["content"] for m in sent_messages]
    assert "short question" in contents
    assert "short answer" in contents


def _note(title: str, body: str) -> Note:
    return Note(slug=title.lower().replace(" ", "-"), title=title, body=body, path=Path(f"/tmp/{title}.md"))


def test_respond_injects_promoted_notes_into_system_prompt():
    llm = MagicMock()
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm)
    promoted = [_note("Key Decision", "We agreed to use Kùzu, not Neo4j.")]

    agent.respond(history=[], user_text="what did we decide?", promoted_notes=promoted)

    sent_messages = llm.complete.call_args[0][0]
    system_content = sent_messages[0]["content"]
    assert "Kùzu, not Neo4j" in system_content
    assert "Key Decision" in system_content
    assert "don't re-litigate" in system_content


def test_respond_with_no_promoted_notes_has_no_established_block():
    llm = MagicMock()
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm)

    agent.respond(history=[], user_text="hello", promoted_notes=None)

    sent_messages = llm.complete.call_args[0][0]
    system_content = sent_messages[0]["content"]
    assert "Already established" not in system_content


def test_respond_promoted_notes_survive_history_truncation():
    # Regression guard for the whole point of this feature: promoted notes
    # must stay in context even when max_history_tokens forces the raw
    # turns that produced them to be dropped.
    llm = MagicMock()
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm, max_history_tokens=1)  # drops virtually all raw history
    promoted = [_note("Settled Point", "The answer was 42.")]
    history = [ChatMessage(role=ChatRole.user, content="x" * 400)]

    agent.respond(history=history, user_text="remind me", promoted_notes=promoted)

    sent_messages = llm.complete.call_args[0][0]
    system_content = sent_messages[0]["content"]
    contents = [m["content"] for m in sent_messages]
    assert "The answer was 42" in system_content
    assert "x" * 400 not in contents


# ── summarize() — Excerpt summary regeneration (ADR-015) ──────────────────────

def test_summarize_sends_system_and_user_content_bypassing_tool_loop():
    llm = MagicMock()
    llm.complete.return_value = "Condensed summary."
    agent = _agent(llm=llm)

    result = agent.summarize("Summarize these turns.", "user: hi\nassistant: hello")

    assert result == "Condensed summary."
    sent_messages = llm.complete.call_args[0][0]
    assert sent_messages == [
        {"role": "system", "content": "Summarize these turns."},
        {"role": "user", "content": "user: hi\nassistant: hello"},
    ]


def test_summarize_returns_none_when_llm_unreachable():
    llm = MagicMock()
    llm.complete.return_value = None
    agent = _agent(llm=llm)

    assert agent.summarize("sys", "content") is None


# ── excerpt_mode() — ADR-015's compressed-vs-verbatim threshold ───────────────

def test_excerpt_mode_always_compressed_on_a_small_context_window_regardless_of_size():
    # Regression guard: a percentage-only check would flip to verbatim for
    # any small pinned turn, even on today's local model — observed live as
    # "pinning one item never shows a Summary at all." A small backend
    # window must never produce verbatim mode, no matter how tiny the
    # pinned content is.
    llm = MagicMock()
    llm.context_window = 32768  # today's local prisma-llm:7b
    agent = _agent(llm=llm)

    tiny_text = "x" * 40  # ~10 tokens — trivially small

    assert agent.excerpt_mode(tiny_text) == "compressed"


def test_excerpt_mode_compressed_when_pinned_content_large_relative_to_a_large_window():
    llm = MagicMock()
    llm.context_window = 1_000_000  # a future large-context cloud backend
    agent = _agent(llm=llm)

    large_text = "x" * 700_000  # ~175000 tokens, well over 15% of 1,000,000

    assert agent.excerpt_mode(large_text) == "compressed"


def test_excerpt_mode_verbatim_on_a_large_context_window_with_small_pinned_set():
    llm = MagicMock()
    llm.context_window = 1_000_000  # a future large-context cloud backend
    agent = _agent(llm=llm)

    small_text = "x" * 40000  # ~10000 tokens, well under 15% of 1,000,000

    assert agent.excerpt_mode(small_text) == "verbatim"


# ── context_usage() — the context label's two numbers ────────────────────────

def test_context_usage_returns_max_history_tokens_as_the_denominator():
    llm = MagicMock()
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm, max_history_tokens=16000)

    _, maximum = agent.context_usage(history=[])

    assert maximum == 16000


def test_context_usage_counts_system_prompt_and_bounded_history():
    llm = MagicMock()
    agent = _agent(llm=llm, max_history_tokens=16000)
    history = [ChatMessage(role=ChatRole.user, content="x" * 400)]

    used, _ = agent.context_usage(history=history)

    # system prompt + tool section alone already costs something — adding a
    # real turn must push it strictly higher.
    baseline, _ = agent.context_usage(history=[])
    assert used > baseline


def test_context_usage_includes_promoted_notes_in_the_count():
    llm = MagicMock()
    agent = _agent(llm=llm, max_history_tokens=16000)
    promoted = [_note("Excerpt", "x" * 4000)]

    with_excerpt, _ = agent.context_usage(history=[], promoted_notes=promoted)
    without_excerpt, _ = agent.context_usage(history=[])

    assert with_excerpt > without_excerpt
