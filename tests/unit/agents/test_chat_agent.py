"""Unit tests for the bounded, pattern-based chat tool loop."""
from pathlib import Path
from unittest.mock import MagicMock

from prisma.agents.chat_agent import MAX_TOOL_ITERATIONS, ChatAgent, _extract_claims, _turn_had_no_grounding
from prisma.schema_gov import RichContent
from prisma.services.chat_tools import ToolResult
from prisma.storage.models.vault_models import ChatRole, CitedClaimNode, InferenceNode, Note, ToolCallNode, TurnNode


def _msg(role: ChatRole, text: str) -> TurnNode:
    return TurnNode(role=role, content=RichContent(value=text))


def _agent(llm=None, toolbox=None, max_history_tokens=16000):
    if llm is None:
        # Unconfigured MagicMock.model would be a MagicMock, not a real
        # string -- TurnNode.model (str | None) rejects that at
        # construction time, in every respond() return path.
        llm = MagicMock()
        llm.model = "test-model"
        llm.context_window = 1_000_000
        llm.has_native_reasoning = True
    if toolbox is None:
        # Unconfigured MagicMock.get_node_text() would return a truthy
        # MagicMock, not real text or None -- _verify_claim would then
        # try to slice/join it and blow up. None means "can't resolve this
        # source," which _verify_claim already handles by skipping the
        # check, so tests that don't care about faithfulness_checked (most
        # of them) aren't forced to configure this explicitly.
        toolbox = MagicMock()
        toolbox.get_node_text.return_value = None
    return ChatAgent(
        llm=llm,
        toolbox=toolbox,
        max_history_tokens=max_history_tokens,
        system_prompt="You are a test assistant.",
    )


def test_reachable_proxies_to_llm():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.reachable.return_value = True
    agent = _agent(llm=llm)

    assert agent.reachable() is True
    llm.reachable.assert_called_once_with()


def test_respond_returns_direct_answer_with_no_tool_call():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "LLM stands for Large Language Model."
    agent = _agent(llm=llm)

    reply = agent.respond(history=[], user_text="What does LLM stand for?")

    assert reply.role == ChatRole.assistant
    # No FOOTNOTES_JSON line in the mocked reply -- _extract_claims wraps it
    # as a single ai-inference claim rather than dropping attribution silently.
    assert reply.content.value == "LLM stands for Large Language Model. [^1]"
    assert reply.tool_calls == []


def test_respond_calls_tool_then_returns_final_answer():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        "SEARCH_VAULT: attention mechanisms",
        "Based on your notes, attention mechanisms let models weigh tokens.",
    ]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="<untrusted_source>...</untrusted_source>", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="What have I written about attention?")

    toolbox.call.assert_called_once()
    call_args, call_kwargs = toolbox.call.call_args
    assert call_args == ("SEARCH_VAULT", "attention mechanisms")
    assert "session_graph" in call_kwargs
    assert "remaining_budget" in call_kwargs
    assert reply.content.value == "Based on your notes, attention mechanisms let models weigh tokens. [^1]"


# ── SessionOrchestrator integration (ADR-019 §35/36) ──────────────────────────

def test_respond_passes_a_session_graph_reflecting_history():
    import networkx as nx

    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = ["SEARCH_VAULT: x", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="hit", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)
    history = [_msg(ChatRole.user, "earlier question"), _msg(ChatRole.assistant, "earlier answer")]

    agent.respond(history=history, user_text="follow-up")

    _, call_kwargs = toolbox.call.call_args
    graph = call_kwargs["session_graph"]
    assert isinstance(graph, nx.MultiDiGraph)
    assert graph.has_node(history[0].id)
    assert graph.has_node(history[1].id)
    assert graph.has_edge(history[0].id, history[1].id)


def test_respond_passes_remaining_budget_reflecting_context_window():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 4000  # generous headroom above the real system+tool+footnote prompt size
    llm.complete.side_effect = ["SEARCH_VAULT: x", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="hit", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    agent.respond(history=[], user_text="short question")

    _, call_kwargs = toolbox.call.call_args
    assert 0 < call_kwargs["remaining_budget"] < 4000


def test_respond_collects_recall_hits_into_recalls():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = ["RECALL: that earlier thing", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="recalled text", raw=[{"node_id": "abc123", "kind": "turn"}])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="remind me")

    assert len(reply.recalls) == 1
    assert reply.recalls[0].node_id == "abc123"
    assert reply.recalls[0].node_kind == "turn"
    # tool_calls still records that RECALL ran, same as any other tool
    assert reply.tool_calls[0].tool == "recall"


def test_respond_forwards_chat_slug_to_toolbox():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = ["RECALL: earlier thing", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="hit", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    agent.respond(history=[], user_text="remind me", chat_slug="my-chat")

    _, call_kwargs = toolbox.call.call_args
    assert call_kwargs["chat_slug"] == "my-chat"


def test_respond_without_chat_slug_passes_none_to_toolbox():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = ["RECALL: earlier thing", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="hit", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    agent.respond(history=[], user_text="remind me")  # chat_slug omitted

    _, call_kwargs = toolbox.call.call_args
    assert call_kwargs["chat_slug"] is None


def test_respond_preserves_cross_chat_slug_on_recall_hits():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = ["RECALL: earlier thing", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(
        text="recalled text",
        raw=[{"node_id": "abc123", "kind": "turn", "chat_slug": "other-chat"}],
    )
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="remind me", chat_slug="my-chat")

    assert reply.recalls[0].chat_slug == "other-chat"


def test_respond_non_recall_tool_calls_leave_recalls_empty():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = ["SEARCH_VAULT: x", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="hit", raw=[{"source_file": "x.md", "score": 0.9, "text": "..."}])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="question")

    assert reply.recalls == []
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].tool == "search_vault"


def test_respond_records_a_think_step_without_a_tool_calls_entry():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.has_native_reasoning = False
    llm.complete.side_effect = ["THINK: checking whether the source supports this", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="(thought recorded)", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="question")

    assert len(reply.thoughts) == 1
    assert reply.thoughts[0].thought == "checking whether the source supports this"
    assert reply.thoughts[0].thought_number == 1
    # Diverted entirely into thoughts -- no duplicate entry under tool_calls.
    assert reply.tool_calls == []


def test_respond_increments_thought_number_across_multiple_think_calls():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.has_native_reasoning = False
    llm.complete.side_effect = ["THINK: step one", "THINK: step two", "final answer"]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="(thought recorded)", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="question")

    assert [t.thought_number for t in reply.thoughts] == [1, 2]
    assert [t.thought for t in reply.thoughts] == ["step one", "step two"]


def test_respond_preserves_thoughts_when_max_tool_iterations_exhausted():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.has_native_reasoning = False
    llm.complete.return_value = "THINK: still working on it"  # never stops thinking
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="(thought recorded)", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="loop forever")

    assert len(reply.thoughts) == MAX_TOOL_ITERATIONS
    assert reply.tool_calls == []
    assert "wasn't able to reach a final answer" in reply.content.value


def test_respond_returns_fallback_when_llm_unreachable():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = None
    agent = _agent(llm=llm)

    reply = agent.respond(history=[], user_text="hello")

    assert "couldn't reach" in reply.content.value.lower()


def test_respond_includes_blocked_reason_when_provided():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = None
    agent = ChatAgent(
        llm=llm,
        toolbox=MagicMock(),
        system_prompt="You are a test assistant.",
        blocked_reason=lambda: "the knowledge graph is currently indexing your vault",
    )

    reply = agent.respond(history=[], user_text="hello")

    assert "knowledge graph is currently indexing" in reply.content.value


def test_respond_fallback_has_no_extra_detail_when_reason_is_none():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = None
    agent = ChatAgent(
        llm=llm, toolbox=MagicMock(), system_prompt="You are a test assistant.",
        blocked_reason=lambda: None,
    )

    reply = agent.respond(history=[], user_text="hello")

    assert reply.content.value == "Sorry, I couldn't reach the language model just now. Please try again shortly."


def test_respond_sends_vault_overview_in_the_system_prompt_when_provided():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.has_native_reasoning = True
    llm.complete.return_value = "final answer"
    agent = ChatAgent(
        llm=llm, toolbox=MagicMock(), system_prompt="You are a test assistant.",
        vault_overview=lambda: ["A", "B", "C", "D", "E"],
    )

    agent.respond(history=[], user_text="hello")

    sent_messages = llm.complete.call_args[0][0]
    assert "knowledge graph currently centers on" in sent_messages[0]["content"]


def test_max_history_tokens_defaults_to_half_the_context_window_when_omitted():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 128_000
    llm.has_native_reasoning = True
    agent = ChatAgent(llm=llm, toolbox=MagicMock(), system_prompt="You are a test assistant.")

    used, maximum = agent.context_usage(history=[])

    assert maximum == 64_000  # half of 128_000 -- not the old flat 16_000


def test_max_history_tokens_explicit_value_is_not_overridden():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 128_000
    llm.has_native_reasoning = True
    agent = ChatAgent(
        llm=llm, toolbox=MagicMock(), system_prompt="You are a test assistant.",
        max_history_tokens=5_000,
    )

    _, maximum = agent.context_usage(history=[])

    assert maximum == 5_000


def test_respond_stops_after_max_tool_iterations():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "SEARCH_VAULT: something"  # never stops calling tools
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="some result", raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="loop forever")

    assert toolbox.call.call_count == MAX_TOOL_ITERATIONS
    assert len(reply.tool_calls) == MAX_TOOL_ITERATIONS
    assert "wasn't able to reach a final answer" in reply.content.value


def test_respond_returns_overflow_message_without_calling_llm_when_assembly_exceeds_context_window():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 100  # ~400 chars -- trivially small
    agent = _agent(llm=llm)

    reply = agent.respond(history=[], user_text="x" * 1000)  # ~250 tokens, over the 100-token window

    llm.complete.assert_not_called()
    assert "context window" in reply.content.value
    assert "test-model" in reply.content.value
    assert "Remove some pinned turns" in reply.content.value
    assert reply.model == "test-model"


def test_respond_checks_context_window_again_after_a_tool_result_grows_the_assembly():
    llm = MagicMock()
    llm.model = "test-model"
    # Fits the initial system+history+user assembly (~1100 estimated tokens
    # for this agent's system prompt), but not once a big tool result's
    # text (~1000 more estimated tokens) gets appended to messages for the
    # second completion call.
    llm.context_window = 1500
    llm.complete.return_value = "SEARCH_VAULT: something"
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="y" * 4000, raw=[])
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="short question")

    assert llm.complete.call_count == 1  # only the call that triggered the tool call
    assert "context window" in reply.content.value
    assert len(reply.tool_calls) == 1


def test_respond_includes_prior_history_in_messages():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "sure, following up on that"
    agent = _agent(llm=llm)
    history = [
        _msg(ChatRole.user, "first question"),
        _msg(ChatRole.assistant, "first answer"),
    ]

    agent.respond(history=history, user_text="follow-up question")

    sent_messages = llm.complete.call_args[0][0]
    roles_and_content = [(m["role"], m["content"]) for m in sent_messages]
    assert ("user", "first question") in roles_and_content
    assert ("assistant", "first answer") in roles_and_content
    assert ("user", "follow-up question") in roles_and_content


def test_respond_drops_oldest_history_once_token_budget_exceeded():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "ok"
    # Budget for ~40 tokens (160 chars at the len//4 heuristic) — enough for
    # only the most recent message, not the oldest one.
    agent = _agent(llm=llm, max_history_tokens=40)
    history = [
        _msg(ChatRole.user, "x" * 200),  # ~50 tokens — too old, dropped
        _msg(ChatRole.assistant, "y" * 100),  # ~25 tokens — kept
    ]

    agent.respond(history=history, user_text="latest question")

    sent_messages = llm.complete.call_args[0][0]
    contents = [m["content"] for m in sent_messages]
    assert "x" * 200 not in contents
    assert "y" * 100 in contents


def test_respond_keeps_all_history_within_budget():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm, max_history_tokens=16000)
    history = [
        _msg(ChatRole.user, "short question"),
        _msg(ChatRole.assistant, "short answer"),
    ]

    agent.respond(history=history, user_text="another question")

    sent_messages = llm.complete.call_args[0][0]
    contents = [m["content"] for m in sent_messages]
    assert "short question" in contents
    assert "short answer" in contents


def _note(title: str, body: str) -> Note:
    return Note(slug=title.lower().replace(" ", "-"), title=title, body=body, path=Path(f"/tmp/{title}.md"))


def test_respond_injects_excerpt_notes_into_system_prompt():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm)
    excerpt = [_note("Key Decision", "We agreed to use Kùzu, not Neo4j.")]

    agent.respond(history=[], user_text="what did we decide?", excerpt_notes=excerpt)

    sent_messages = llm.complete.call_args[0][0]
    system_content = sent_messages[0]["content"]
    assert "Kùzu, not Neo4j" in system_content
    assert "Key Decision" in system_content
    assert "don't re-litigate" in system_content


def test_respond_with_no_excerpt_notes_has_no_established_block():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm)

    agent.respond(history=[], user_text="hello", excerpt_notes=None)

    sent_messages = llm.complete.call_args[0][0]
    system_content = sent_messages[0]["content"]
    assert "Already established" not in system_content


def test_respond_excerpt_notes_survive_history_truncation():
    # Regression guard for the whole point of this feature: excerpt notes
    # must stay in context even when max_history_tokens forces the raw
    # turns that produced them to be dropped.
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm, max_history_tokens=1)  # drops virtually all raw history
    excerpt = [_note("Settled Point", "The answer was 42.")]
    history = [_msg(ChatRole.user, "x" * 400)]

    agent.respond(history=history, user_text="remind me", excerpt_notes=excerpt)

    sent_messages = llm.complete.call_args[0][0]
    system_content = sent_messages[0]["content"]
    contents = [m["content"] for m in sent_messages]
    assert "The answer was 42" in system_content
    assert "x" * 400 not in contents


# ── complete_once() — one-shot completions (ADR-015 excerpt summary, ─────────
# ── ADR-017 faithfulness verification), bypassing the tool loop ──────────────

def test_complete_once_sends_system_and_user_content_bypassing_tool_loop():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "Condensed summary."
    agent = _agent(llm=llm)

    result = agent.complete_once("Summarize these turns.", "user: hi\nassistant: hello")

    assert result == "Condensed summary."
    sent_messages = llm.complete.call_args[0][0]
    assert sent_messages == [
        {"role": "system", "content": "Summarize these turns."},
        {"role": "user", "content": "user: hi\nassistant: hello"},
    ]


def test_complete_once_returns_none_when_llm_unreachable():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = None
    agent = _agent(llm=llm)

    assert agent.complete_once("sys", "content") is None


# ── excerpt_mode() — ADR-015's compressed-vs-verbatim threshold ───────────────

def test_excerpt_mode_always_compressed_on_a_small_context_window_regardless_of_size():
    # Regression guard: a percentage-only check would flip to verbatim for
    # any small pinned turn, even on today's local model — observed live as
    # "pinning one item never shows a Summary at all." A small backend
    # window must never produce verbatim mode, no matter how tiny the
    # pinned content is.
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 32768  # today's local qwen2.5:7b-32k
    agent = _agent(llm=llm)

    tiny_text = "x" * 40  # ~10 tokens — trivially small

    assert agent.excerpt_mode(tiny_text) == "compressed"


def test_excerpt_mode_compressed_when_pinned_content_large_relative_to_a_large_window():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000  # a future large-context cloud backend
    agent = _agent(llm=llm)

    large_text = "x" * 700_000  # ~175000 tokens, well over 15% of 1,000,000

    assert agent.excerpt_mode(large_text) == "compressed"


def test_excerpt_mode_verbatim_on_a_large_context_window_with_small_pinned_set():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000  # a future large-context cloud backend
    agent = _agent(llm=llm)

    small_text = "x" * 40000  # ~10000 tokens, well under 15% of 1,000,000

    assert agent.excerpt_mode(small_text) == "verbatim"


# ── context_usage() — the context label's two numbers ────────────────────────

def test_context_usage_returns_max_history_tokens_as_the_denominator():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm, max_history_tokens=16000)

    _, maximum = agent.context_usage(history=[])

    assert maximum == 16000


def test_context_usage_counts_system_prompt_and_bounded_history():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    agent = _agent(llm=llm, max_history_tokens=16000)
    history = [_msg(ChatRole.user, "x" * 400)]

    used, _ = agent.context_usage(history=history)

    # system prompt + tool section alone already costs something — adding a
    # real turn must push it strictly higher.
    baseline, _ = agent.context_usage(history=[])
    assert used > baseline


def test_context_usage_includes_excerpt_notes_in_the_count():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    agent = _agent(llm=llm, max_history_tokens=16000)
    excerpt = [_note("Excerpt", "x" * 4000)]

    with_excerpt, _ = agent.context_usage(history=[], excerpt_notes=excerpt)
    without_excerpt, _ = agent.context_usage(history=[])

    assert with_excerpt > without_excerpt


# ── _extract_claims() — ADR-017 claim attribution self-report ────────────────

def test_extract_claims_parses_a_well_formed_report():
    reply = (
        'Transformers use self-attention[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "citation", "sources": ["attention-paper"]}]'
    )

    content, claims = _extract_claims(reply)

    assert content == "Transformers use self-attention[^1]."
    assert len(claims) == 1
    assert isinstance(claims[0], CitedClaimNode)
    assert claims[0].index == 1
    assert claims[0].relation == "citation"
    assert claims[0].sources == ["attention-paper"]


def test_extract_claims_parses_a_paraphrase_relation():
    reply = (
        'Attention lets models weigh different input tokens[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "paraphrase", "sources": ["attention-paper"]}]'
    )

    _, claims = _extract_claims(reply)

    assert len(claims) == 1
    assert isinstance(claims[0], CitedClaimNode)
    assert claims[0].relation == "paraphrase"


def test_extract_claims_strips_the_line_even_when_list_is_empty():
    reply = "Just chatting, no claims here.\nFOOTNOTES_JSON: []"

    content, claims = _extract_claims(reply)

    assert content == "Just chatting, no claims here."
    assert claims == []


def test_extract_claims_wraps_reply_as_inference_when_line_missing():
    # A model that ignores the instruction entirely must not lose its
    # answer -- this is the single most important fallback in the whole
    # feature, since claim attribution is new prompting complexity layered
    # on an existing, already-working chat loop. But it also must not pass
    # through with zero trust signal (ADR-017: an unmarked substantive claim
    # is exactly as bad as a factual error) -- confirmed live in production,
    # a real chat turn skipped FOOTNOTES_JSON entirely and its factual
    # content rendered with no [^N] marker and no References block at all.
    reply = "No footnote line at all here."

    content, claims = _extract_claims(reply)

    assert content == "No footnote line at all here. [^1]"
    assert len(claims) == 1
    assert claims[0].kind == "inference"
    assert claims[0].index == 1
    assert claims[0].claim_text == "No footnote line at all here."


def test_extract_claims_returns_no_claims_for_empty_reply():
    content, claims = _extract_claims("   ")

    assert content == ""
    assert claims == []


def test_extract_claims_drops_all_on_malformed_json_but_keeps_content():
    reply = "Some answer.\nFOOTNOTES_JSON: {not valid json"

    content, claims = _extract_claims(reply)

    assert content == "Some answer."
    assert claims == []


def test_extract_claims_skips_only_the_malformed_entry():
    reply = (
        "Two claims here.\n"
        'FOOTNOTES_JSON: [{"index": 1, "relation": "citation", "sources": ["a"]}, '
        '{"index": 2, "relation": "not-a-real-relation", "sources": ["b"]}]'
    )

    content, claims = _extract_claims(reply)

    assert content == "Two claims here."
    assert len(claims) == 1
    assert claims[0].index == 1


def test_extract_claims_uses_the_last_match_if_model_discusses_format_first():
    reply = (
        'I will use FOOTNOTES_JSON: [] as my format.\n'
        "The actual answer[^1].\n"
        'FOOTNOTES_JSON: [{"index": 1, "relation": "ai-inference", "sources": []}]'
    )

    content, claims = _extract_claims(reply)

    assert "The actual answer[^1]." in content
    assert len(claims) == 1
    assert isinstance(claims[0], InferenceNode)


def test_respond_final_answer_populates_claims():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = (
        'Kùzu was chosen for its embedded mode[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["kg-decision"]}]'
    )
    agent = _agent(llm=llm)

    reply = agent.respond(history=[], user_text="why Kùzu?")

    assert reply.content.value == "Kùzu was chosen for its embedded mode[^1]."
    assert len(reply.claims) == 1
    assert reply.claims[0].sources == ["kg-decision"]


def test_respond_final_answer_with_no_footnotes_line_is_wrapped_as_inference():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "A plain answer with no sourcing."
    agent = _agent(llm=llm)

    reply = agent.respond(history=[], user_text="hello")

    assert len(reply.claims) == 1
    assert reply.claims[0].kind == "inference"


# ── deterministic no-grounding override ──────────────────────────────────
# Confirmed live in production (2026-08-27): a grounding tool call that came
# back empty still let unmarked or wrongly-marked content through, three
# different ways depending on what the model's self-report happened to look
# like that turn. Fixed by deriving the classification from ToolCallNode
# data ChatAgent itself built, instead of trusting the model's self-report
# in this one case -- see _turn_had_no_grounding()'s docstring.

def test_turn_had_no_grounding_true_when_grounding_tool_returned_nothing():
    tool_calls = [ToolCallNode(tool="search_vault", args={"query": "x"}, result=None, status="ok")]

    assert _turn_had_no_grounding(tool_calls) is True


def test_turn_had_no_grounding_false_when_grounding_tool_returned_content():
    tool_calls = [ToolCallNode(tool="search_vault", args={"query": "x"}, result="a hit", status="ok")]

    assert _turn_had_no_grounding(tool_calls) is False


def test_turn_had_no_grounding_false_when_no_grounding_tool_was_called():
    # RECALL isn't a grounding tool (session history, not vault documents) --
    # a turn that only ever called RECALL is left to the existing self-report
    # path, same as one that called no tool at all.
    tool_calls = [ToolCallNode(tool="recall", args={"query": "x"}, result=None, status="ok")]

    assert _turn_had_no_grounding(tool_calls) is False


def test_turn_had_no_grounding_false_when_zotero_search_returned_content():
    # Copilot review on PR #97: search_vault empty + zotero_search real
    # hits must not be forced into one inference block -- zotero_search is
    # just as much a grounding tool as search_vault/graph_context.
    tool_calls = [
        ToolCallNode(tool="search_vault", args={"query": "x"}, result=None, status="ok"),
        ToolCallNode(tool="zotero_search", args={"query": "x"}, result="a Zotero abstract", status="ok"),
    ]

    assert _turn_had_no_grounding(tool_calls) is False


def test_respond_overrides_self_report_when_grounding_tool_returns_nothing():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        "SEARCH_VAULT: low-resource LLMs",
        'It seems there are no notes on this. I can share general knowledge if you want.\n'
        'FOOTNOTES_JSON: []',
    ]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="", raw=[])  # nothing found
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="low-resource LLMs?")

    assert reply.content.value == (
        "It seems there are no notes on this. I can share general knowledge if you want. [^1]"
    )
    assert len(reply.claims) == 1
    assert reply.claims[0].kind == "inference"
    assert reply.claims[0].claim_text == (
        "It seems there are no notes on this. I can share general knowledge if you want."
    )


def test_respond_does_not_override_when_grounding_tool_returns_content():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        "SEARCH_VAULT: kuzu",
        'Kùzu was chosen for its embedded mode[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["kg-decision"]}]',
    ]
    toolbox = MagicMock()
    toolbox.call.return_value = ToolResult(text="Kùzu docs excerpt", raw=[])
    toolbox.slug_resolves.return_value = True
    toolbox.get_node_text.return_value = None  # skip faithfulness_checked, see _agent()'s docstring
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="why Kùzu?")

    assert reply.content.value == "Kùzu was chosen for its embedded mode[^1]."
    assert len(reply.claims) == 1
    assert reply.claims[0].sources == ["kg-decision"]


def test_system_prompt_includes_footnote_instructions():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = "ok"
    agent = _agent(llm=llm)

    agent.respond(history=[], user_text="hello")

    sent_messages = llm.complete.call_args[0][0]
    system_content = sent_messages[0]["content"]
    assert "FOOTNOTES_JSON" in system_content
    assert "ai-inference" in system_content


# ── claim_text extraction (ADR-017's faithfulness_checked input) ─────────────

def test_extract_claims_populates_claim_text_from_preceding_sentence():
    reply = (
        'Kùzu has no server process. It was chosen for its embedded mode[^1]. '
        'Neo4j needs a JVM[^2].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["a"]}, '
        '{"index": 2, "relation": "attribution", "sources": ["b"]}]'
    )

    _, claims = _extract_claims(reply)

    assert claims[0].claim_text == "It was chosen for its embedded mode"
    assert claims[1].claim_text == "Neo4j needs a JVM"


def test_extract_claims_claim_text_empty_when_no_markers_in_content():
    # Malformed input the model never actually produces (a FOOTNOTES_JSON
    # entry with no matching [^N] in the text) -- must degrade gracefully
    # to an empty claim_text (CitedClaimNode/InferenceNode.claim_text is
    # non-optional, unlike v1's Footnote), not raise a KeyError.
    reply = 'No markers here.\nFOOTNOTES_JSON: [{"index": 1, "relation": "ai-inference", "sources": []}]'

    _, claims = _extract_claims(reply)

    assert claims[0].claim_text == ""


# ── faithfulness_checked verification (ADR-017, automatic every turn) ────────

def test_respond_faithfulness_checked_true_when_verifier_says_yes():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'Kùzu is embedded, no server process[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["kg-decision"]}]',
        "YES",
    ]
    toolbox = MagicMock()
    toolbox.get_node_text.return_value = "Kùzu runs embedded in-process, with no separate server."
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="why Kùzu?")

    assert reply.claims[0].faithfulness_checked is True
    toolbox.get_node_text.assert_called_once_with("kg-decision")
    # Second complete() call is the verification prompt, not another chat turn.
    verify_messages = llm.complete.call_args_list[1][0][0]
    assert verify_messages[0]["role"] == "system"
    assert "fact-checker" in verify_messages[0]["content"].lower()
    assert "Kùzu is embedded, no server process" in verify_messages[1]["content"]


def test_respond_corrects_relation_when_verifier_suggests_a_different_one():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'This could relate to how Kùzu handles concurrency[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "citation", "sources": ["kg-decision"]}]',
        "YES attribution",
    ]
    toolbox = MagicMock()
    toolbox.get_node_text.return_value = "Kùzu runs embedded in-process, with no separate server."
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="why Kùzu?")

    assert reply.claims[0].relation == "attribution"
    assert reply.claims[0].faithfulness_checked is True


def test_respond_leaves_relation_unchanged_when_verifier_reply_has_no_relation_token():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'Kùzu is embedded, no server process[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["kg-decision"]}]',
        "YES",  # old-style single-token reply -- must not crash or guess a relation
    ]
    toolbox = MagicMock()
    toolbox.get_node_text.return_value = "Kùzu runs embedded in-process, with no separate server."
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="why Kùzu?")

    assert reply.claims[0].relation == "attribution"
    assert reply.claims[0].faithfulness_checked is True


def test_respond_forces_relational_for_multi_source_claims_regardless_of_self_report():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'ROME and MEMIT both edit model weights[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "citation", "sources": ["rome-paper", "memit-paper"]}]',
        "YES citation",  # even if the verifier disagrees, source count wins -- structural, not judged
    ]
    toolbox = MagicMock()
    toolbox.get_node_text.return_value = "Some source text."
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="how do ROME and MEMIT compare?")

    assert reply.claims[0].relation == "relational"


def test_respond_drops_claim_citing_an_unresolvable_slug():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'Kùzu is embedded, no server process[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["made-up-slug"]}]',
    ]
    toolbox = MagicMock()
    toolbox.slug_resolves.return_value = False
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="why Kùzu?")

    assert reply.claims == []
    toolbox.slug_resolves.assert_called_once_with("made-up-slug")


def test_respond_keeps_claim_when_all_sources_resolve():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'Kùzu is embedded, no server process[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["kg-decision"]}]',
    ]
    toolbox = MagicMock()
    toolbox.slug_resolves.return_value = True
    toolbox.get_node_text.return_value = None  # skip the faithfulness LLM call
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="why Kùzu?")

    assert len(reply.claims) == 1
    assert reply.claims[0].sources == ["kg-decision"]


def test_respond_inference_claims_never_check_source_resolution():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'This is my own reasoning[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "ai-inference", "sources": []}]',
    ]
    toolbox = MagicMock()
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="what do you think?")

    assert len(reply.claims) == 1
    toolbox.slug_resolves.assert_not_called()


def test_respond_faithfulness_checked_false_when_verifier_says_no():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'Kùzu requires a JVM[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["kg-decision"]}]',
        "NO",
    ]
    toolbox = MagicMock()
    toolbox.get_node_text.return_value = "Kùzu is embedded and needs no JVM."
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="why Kùzu?")

    assert reply.claims[0].faithfulness_checked is False


def test_respond_faithfulness_checked_none_when_source_unresolvable():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = (
        'A claim[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["missing-slug"]}]'
    )
    toolbox = MagicMock()
    toolbox.get_node_text.return_value = None  # stale/hallucinated slug
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="hello")

    assert reply.claims[0].faithfulness_checked is None
    assert llm.complete.call_count == 1  # no verification call made


def test_respond_faithfulness_checked_none_when_verifier_unreachable():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.side_effect = [
        'A claim[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "attribution", "sources": ["a"]}]',
        None,  # verification call fails
    ]
    toolbox = MagicMock()
    toolbox.get_node_text.return_value = "some source text"
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="hello")

    assert reply.claims[0].faithfulness_checked is None


def test_respond_ai_inference_claim_never_triggers_verification():
    llm = MagicMock()
    llm.model = "test-model"
    llm.context_window = 1_000_000
    llm.complete.return_value = (
        'Just my own reasoning[^1].\n'
        'FOOTNOTES_JSON: [{"index": 1, "relation": "ai-inference", "sources": []}]'
    )
    toolbox = MagicMock()
    agent = _agent(llm=llm, toolbox=toolbox)

    reply = agent.respond(history=[], user_text="hello")

    assert isinstance(reply.claims[0], InferenceNode)  # structurally has no faithfulness_checked to verify
    toolbox.get_node_text.assert_not_called()
    assert llm.complete.call_count == 1
