"""Unit tests for SessionOrchestrator (ADR-019, chat-session-graph.md) --
default context assembly and the in-memory session graph builder."""
from pathlib import Path

from prisma.agents.session_orchestrator import SessionOrchestrator
from prisma.schema_gov import RichContent
from prisma.storage.models.vault_models import (
    Chat, ChatRole, CitedClaimNode, InferenceNode, Note, ThinkingNode, ToolCallNode, TurnNode,
)


def _orchestrator(max_history_tokens=16000, has_native_reasoning=True, vault_overview=None) -> SessionOrchestrator:
    return SessionOrchestrator(
        system_prompt="You are a test assistant.", max_history_tokens=max_history_tokens,
        has_native_reasoning=has_native_reasoning, vault_overview=vault_overview,
    )


def _msg(role: ChatRole, text: str, **overrides) -> TurnNode:
    return TurnNode(role=role, content=RichContent(value=text), **overrides)


def _note(title: str, body: str) -> Note:
    return Note(slug=title.lower().replace(" ", "-"), title=title, body=body, path=Path(f"/tmp/{title}.md"))


def _chat(**overrides) -> Chat:
    defaults = dict(slug="test-chat", title="Test Chat", path=Path("/tmp/test-chat.sess"))
    defaults.update(overrides)
    return Chat(**defaults)


# ── full_system_prompt() ──────────────────────────────────────────────────

def test_full_system_prompt_includes_tool_and_footnote_sections():
    orch = _orchestrator()
    prompt = orch.full_system_prompt([])
    assert "You are a test assistant." in prompt
    assert "FOOTNOTES_JSON" in prompt


def test_full_system_prompt_with_no_excerpt_notes_has_no_established_block():
    orch = _orchestrator()
    prompt = orch.full_system_prompt([])
    assert "Already established" not in prompt


def test_full_system_prompt_hides_think_when_native_reasoning_true():
    orch = _orchestrator(has_native_reasoning=True)
    assert "THINK:" not in orch.full_system_prompt([])


def test_full_system_prompt_shows_think_when_native_reasoning_false():
    orch = _orchestrator(has_native_reasoning=False)
    assert "THINK:" in orch.full_system_prompt([])


def test_full_system_prompt_omits_vault_overview_block_when_callable_is_none():
    orch = _orchestrator()
    assert "knowledge graph currently centers on" not in orch.full_system_prompt([])


def test_full_system_prompt_omits_vault_overview_block_below_min_entities():
    orch = _orchestrator(vault_overview=lambda: ["A", "B"])
    assert "knowledge graph currently centers on" not in orch.full_system_prompt([])


def test_full_system_prompt_includes_vault_overview_block_when_above_threshold():
    labels = ["A", "B", "C", "D", "E"]
    orch = _orchestrator(vault_overview=lambda: labels)
    prompt = orch.full_system_prompt([])
    assert "knowledge graph currently centers on" in prompt
    assert "A, B, C, D, E" in prompt


def test_full_system_prompt_calls_vault_overview_fresh_each_call():
    calls = []

    def _labels():
        calls.append(1)
        return ["A", "B", "C", "D", "E"]

    orch = _orchestrator(vault_overview=_labels)
    orch.full_system_prompt([])
    orch.full_system_prompt([])
    assert len(calls) == 2


def test_full_system_prompt_injects_excerpt_notes():
    orch = _orchestrator()
    excerpt = [_note("Key Decision", "We agreed to use Kùzu, not Neo4j.")]
    prompt = orch.full_system_prompt(excerpt)
    assert "Kùzu, not Neo4j" in prompt
    assert "Key Decision" in prompt
    assert "don't re-litigate" in prompt


# ── bounded_history() ──────────────────────────────────────────────────────

def test_bounded_history_drops_oldest_once_budget_exceeded():
    orch = _orchestrator(max_history_tokens=40)  # ~160 chars
    history = [
        _msg(ChatRole.user, "x" * 200),  # ~50 tokens -- too old, dropped
        _msg(ChatRole.assistant, "y" * 100),  # ~25 tokens -- kept
    ]
    kept = orch.bounded_history(history)
    assert [m.content.value for m in kept] == ["y" * 100]


def test_bounded_history_keeps_everything_within_budget():
    orch = _orchestrator(max_history_tokens=16000)
    history = [_msg(ChatRole.user, "short question"), _msg(ChatRole.assistant, "short answer")]
    kept = orch.bounded_history(history)
    assert [m.content.value for m in kept] == ["short question", "short answer"]


# ── graph_for() ────────────────────────────────────────────────────────────

def test_graph_for_connects_main_line_turns_via_next():
    chat = _chat(messages=[_msg(ChatRole.user, "hi"), _msg(ChatRole.assistant, "hello")])
    g = _orchestrator().graph_for(chat.messages)

    t0, t1 = chat.messages[0].id, chat.messages[1].id
    assert g.has_edge(t0, t1)
    assert g[t0][t1][0]["kind"] == "NEXT"


def test_graph_for_attaches_tool_calls_via_invokes():
    turn = _msg(ChatRole.assistant, "answer", tool_calls=[ToolCallNode(tool="search_vault", args={"query": "x"}, result="hit")])
    chat = _chat(messages=[turn])
    g = _orchestrator().graph_for(chat.messages)

    tc_id = turn.tool_calls[0].id
    assert g.nodes[tc_id]["kind"] == "tool_call"
    assert g.has_edge(turn.id, tc_id)
    assert g[turn.id][tc_id][0]["kind"] == "INVOKES"


def test_graph_for_attaches_thoughts_via_reasons_with_revises_and_branches_from_edges():
    t1 = ThinkingNode(thought="first", thought_number=1)
    t2 = ThinkingNode(thought="revised", thought_number=2, revises=t1.id)
    t3 = ThinkingNode(thought="alt path", thought_number=3, branches_from=t1.id)
    turn = _msg(ChatRole.assistant, "answer", thoughts=[t1, t2, t3])
    chat = _chat(messages=[turn])
    g = _orchestrator().graph_for(chat.messages)

    assert g.has_edge(turn.id, t1.id)
    assert g[turn.id][t1.id][0]["kind"] == "REASONS"
    assert g.has_edge(t2.id, t1.id)
    assert g[t2.id][t1.id][0]["kind"] == "REVISES"
    assert g.has_edge(t3.id, t1.id)
    assert g[t3.id][t1.id][0]["kind"] == "BRANCHES_FROM"


def test_graph_for_attaches_claims_via_asserts():
    claim = CitedClaimNode(index=1, claim_text="x", sources=["a"], relation="citation")
    inference = InferenceNode(index=2, claim_text="y")
    turn = _msg(ChatRole.assistant, "answer[^1][^2]", claims=[claim, inference])
    chat = _chat(messages=[turn])
    g = _orchestrator().graph_for(chat.messages)

    assert g.has_edge(turn.id, claim.id)
    assert g[turn.id][claim.id][0]["kind"] == "ASSERTS"
    assert g.has_edge(turn.id, inference.id)
    assert g[turn.id][inference.id][0]["kind"] == "ASSERTS"


def test_graph_for_attaches_alternates_via_regenerates():
    old_attempt = _msg(ChatRole.assistant, "v1 answer", model="qwen2.5-3b")
    live = _msg(ChatRole.assistant, "v2 answer", model="qwen2.5-7b", alternates=[old_attempt])
    chat = _chat(messages=[live])
    g = _orchestrator().graph_for(chat.messages)

    assert g.has_edge(live.id, old_attempt.id)
    assert g[live.id][old_attempt.id][0]["kind"] == "REGENERATES"


def test_graph_for_empty_chat_has_no_nodes():
    g = _orchestrator().graph_for(_chat().messages)
    assert g.number_of_nodes() == 0
