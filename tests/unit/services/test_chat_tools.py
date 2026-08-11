"""Unit tests for the chat tool registry (pattern-based tool loop)."""
from unittest.mock import MagicMock

import pytest

from prisma.services.chat_tools import TOOL_CALL_RE, ChatToolbox, system_prompt_tool_section
from prisma.services.vault import VaultService
from prisma.storage.models.kg_models import GraphQueryResult
from prisma.storage.models.search_models import GraphSearchResult


def test_system_prompt_tool_section_includes_all_markers():
    text = system_prompt_tool_section()
    assert "SEARCH_VAULT:" in text
    assert "GRAPH_CONTEXT:" in text
    assert "RECALL:" in text


def test_tool_call_re_matches_search_vault_line():
    text = "some preamble\nSEARCH_VAULT: attention mechanisms\nmore text"
    matches = TOOL_CALL_RE.findall(text)
    assert matches == [("SEARCH_VAULT", "attention mechanisms")]


def test_tool_call_re_matches_graph_context_line():
    text = "GRAPH_CONTEXT: sparse autoencoders and interpretability"
    matches = TOOL_CALL_RE.findall(text)
    assert matches == [("GRAPH_CONTEXT", "sparse autoencoders and interpretability")]


def test_tool_call_re_matches_recall_line():
    text = "RECALL: that search result about Kùzu's embedded mode"
    matches = TOOL_CALL_RE.findall(text)
    assert matches == [("RECALL", "that search result about Kùzu's embedded mode")]


def test_tool_call_re_ignores_plain_prose():
    text = "LLM stands for Large Language Model."
    assert TOOL_CALL_RE.findall(text) == []


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def test_toolbox_search_vault_returns_wrapped_text_and_raw(vault):
    note = vault.root / "notes" / "attention.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Attention mechanisms let models weigh input tokens.", encoding="utf-8")

    chroma = MagicMock()
    chroma.query.return_value = [GraphSearchResult(source_file="notes/attention.md", score=0.9)]
    kg = MagicMock()

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("SEARCH_VAULT", "attention")

    assert result.raw == [{"source_file": "notes/attention.md", "score": 0.9,
                            "text": "Attention mechanisms let models weigh input tokens."}]
    # Wrapped under the slug (ADR-017: what a footnote's `sources` expects),
    # not the raw vault-relative path.
    assert 'path="attention"' in result.text
    assert "Attention mechanisms" in result.text


def test_toolbox_search_vault_skips_unreadable_files(vault):
    chroma = MagicMock()
    chroma.query.return_value = [GraphSearchResult(source_file="notes/missing.md", score=0.5)]
    kg = MagicMock()

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("SEARCH_VAULT", "anything")

    assert result.text == ""
    assert result.raw[0]["text"] == ""


def test_toolbox_graph_context_returns_wrapped_text(vault):
    chroma = MagicMock()
    kg = MagicMock()
    kg.query.return_value = [GraphQueryResult(text="- notes/a.md (score=0.8)", sources=["a", "b"])]

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("GRAPH_CONTEXT", "how do these relate")

    assert "notes/a.md" in result.text
    assert 'path="knowledge-graph"' in result.text
    # ADR-017: sources listed explicitly so the model has an unambiguous
    # list to copy into FOOTNOTES_JSON, not just slugs buried in prose.
    assert "Sources: a, b" in result.text
    assert result.raw == [{"text": "- notes/a.md (score=0.8)", "sources": ["a", "b"]}]


def test_toolbox_graph_context_omits_sources_header_when_none(vault):
    chroma = MagicMock()
    kg = MagicMock()
    kg.query.return_value = [GraphQueryResult(text="- notes/a.md (score=0.8)")]

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("GRAPH_CONTEXT", "how do these relate")

    assert "Sources:" not in result.text


def test_toolbox_graph_context_empty_when_no_results(vault):
    chroma = MagicMock()
    kg = MagicMock()
    kg.query.return_value = []

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("GRAPH_CONTEXT", "anything")

    assert result.text == ""
    assert result.raw == []


def test_toolbox_call_unknown_marker_raises(vault):
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)
    with pytest.raises(ValueError, match="unknown tool marker"):
        toolbox.call("NOT_A_TOOL", "query")


# ── get_node_text() — ADR-017 faithfulness_checked's source-text resolver ────

def test_get_node_text_returns_note_body(vault):
    note = vault.create_note("Attention", body="Attention mechanisms let models weigh tokens.")
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    assert toolbox.get_node_text(note.slug) == "Attention mechanisms let models weigh tokens."


def test_get_node_text_joins_chat_messages(vault):
    from prisma.schema_gov import RichContent
    from prisma.storage.models.vault_models import ChatRole, TurnNode

    chat = vault.create_chat(title="Kùzu decision")
    vault.save_chat(chat.slug, [
        TurnNode(role=ChatRole.user, content=RichContent(value="Why Kùzu over Neo4j?")),
        TurnNode(role=ChatRole.assistant, content=RichContent(value="Kùzu is embedded, no JVM needed.")),
    ])
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    text = toolbox.get_node_text(chat.slug)

    assert "Why Kùzu over Neo4j?" in text
    assert "Kùzu is embedded, no JVM needed." in text


def test_get_node_text_returns_none_for_missing_slug(vault):
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    assert toolbox.get_node_text("does-not-exist") is None


def test_get_node_text_returns_none_for_empty_body(vault):
    note = vault.create_note("Empty", body="")
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    assert toolbox.get_node_text(note.slug) is None


# ── slug_resolves() — ADR-020 hard-validation of CitedClaimNode.sources ───────

def test_slug_resolves_true_for_a_real_note(vault):
    note = vault.create_note("Attention", body="text")
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    assert toolbox.slug_resolves(note.slug) is True


def test_slug_resolves_false_for_a_missing_slug(vault):
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    assert toolbox.slug_resolves("does-not-exist") is False


def test_slug_resolves_true_for_a_real_but_empty_note(vault):
    # Unlike get_node_text() (which treats an empty body as unresolved --
    # correct for "is there text to check faithfulness against"), a real
    # slug with an empty body is still a real slug -- correct for "does
    # this claim cite something that actually exists."
    note = vault.create_note("Empty", body="")
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    assert toolbox.slug_resolves(note.slug) is True


# ── RECALL (ADR-019, docs/concepts/chat-session-graph.md) ────────────────────

def _graph_with_two_turns(text_a: str, text_b: str):
    from pathlib import Path

    from prisma.agents.session_orchestrator import SessionOrchestrator
    from prisma.schema_gov import RichContent
    from prisma.storage.models.vault_models import Chat, ChatRole, TurnNode

    chat = Chat(slug="s", title="S", path=Path("/tmp/s.sess"), messages=[
        TurnNode(role=ChatRole.user, content=RichContent(value=text_a)),
        TurnNode(role=ChatRole.assistant, content=RichContent(value=text_b)),
    ])
    graph = SessionOrchestrator(system_prompt="sys", max_history_tokens=16000).graph_for(chat.messages)
    return graph, chat


def test_recall_returns_placeholder_when_graph_is_none(vault):
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=None, remaining_budget=4000)

    assert result.text == "(nothing to recall yet)"
    assert result.raw == []


def test_recall_returns_placeholder_when_graph_is_empty(vault):
    import networkx as nx

    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=nx.MultiDiGraph(), remaining_budget=4000)

    assert result.text == "(nothing to recall yet)"


def test_recall_ranks_candidates_by_embedding_similarity(vault):
    graph, _ = _graph_with_two_turns("apple pie recipe", "banana bread recipe")
    chroma = MagicMock()
    # order: [query, candidate_a (apple), candidate_b (banana)] -- apple matches the query
    chroma.embed_texts.return_value = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "apple recipe", session_graph=graph, remaining_budget=4000)

    assert result.text.index("apple pie recipe") < result.text.index("banana bread recipe")


def test_recall_calls_embed_with_interactive_priority_and_short_max_wait(vault):
    graph, _ = _graph_with_two_turns("a", "b")
    chroma = MagicMock()
    chroma.embed_texts.return_value = [[1.0], [1.0], [1.0]]
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    toolbox.call("RECALL", "q", session_graph=graph, remaining_budget=4000)

    _, kwargs = chroma.embed_texts.call_args
    assert kwargs["priority"] == "interactive"
    assert kwargs["max_wait"] == 0.5


def test_recall_degrades_to_recency_when_embedding_unavailable(vault):
    # embed_texts returning None covers both a denied lease and a failed
    # embed call -- RECALL must never wait or error, only degrade.
    graph, _ = _graph_with_two_turns("first turn", "second turn")
    chroma = MagicMock()
    chroma.embed_texts.return_value = None
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=4000)

    # networkx preserves insertion order (chat.messages order) -- recency
    # fallback is newest-first.
    assert result.text.index("second turn") < result.text.index("first turn")


def test_recall_returns_nothing_found_when_nothing_fits_the_budget(vault):
    graph, _ = _graph_with_two_turns("x" * 4000, "y" * 4000)
    chroma = MagicMock()
    chroma.embed_texts.return_value = None
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=100)

    assert result.text == "(nothing found)"
    assert result.raw == []


def test_recall_packs_greedily_skipping_candidates_that_dont_fit(vault):
    # Recency fallback ranks "y"*4000 (newest) first, but it doesn't fit --
    # packing should skip it and still include the older, smaller "short".
    graph, _ = _graph_with_two_turns("short", "y" * 4000)
    chroma = MagicMock()
    chroma.embed_texts.return_value = None
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=10)

    assert "short" in result.text
    assert "y" * 4000 not in result.text


def test_recall_wraps_result_as_untrusted_content(vault):
    graph, _ = _graph_with_two_turns("a claim from earlier", "another turn")
    chroma = MagicMock()
    chroma.embed_texts.return_value = None
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=4000)

    assert "<untrusted_source" in result.text
    assert result.raw[0]["kind"] == "turn"
    assert "node_id" in result.raw[0]


def test_recall_without_chat_slug_result_has_no_chat_slug(vault):
    # Same-chat-only behavior (no chat_slug passed) must still tag every
    # result chat_slug: None, not omit the key -- RecallRef requires it.
    graph, _ = _graph_with_two_turns("a", "b")
    chroma = MagicMock()
    chroma.embed_texts.return_value = None
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=4000)

    assert all(item["chat_slug"] is None for item in result.raw)


# ── Cross-chat RECALL (raised 2026-08-05, docs/concepts/chat-session-graph.md#status) ─────

def _vault_chat_with_two_turns(vault: VaultService, title: str, text_a: str, text_b: str):
    from prisma.schema_gov import RichContent
    from prisma.storage.models.vault_models import ChatRole, TurnNode

    chat = vault.create_chat(title=title)
    vault.append_messages(chat.slug, [
        TurnNode(role=ChatRole.user, content=RichContent(value=text_a)),
        TurnNode(role=ChatRole.assistant, content=RichContent(value=text_b)),
    ])
    return vault.get_chat(chat.slug)


def test_recall_with_chat_slug_pulls_in_other_chats(vault):
    graph, current = _graph_with_two_turns("current chat turn one", "current chat turn two")
    _vault_chat_with_two_turns(vault, "Other chat", "other chat turn one", "other chat turn two")
    chroma = MagicMock()
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    # 5 texts go in: query + 2 current-chat candidates + 2 other-chat candidates.
    chroma.embed_texts.return_value = [[1.0]] * 5

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=4000, chat_slug=current.slug)

    slugs = {item["chat_slug"] for item in result.raw}
    assert None in slugs  # the current chat's own candidates
    assert any(s is not None for s in slugs)  # at least one cross-chat candidate got in
    assert "other chat turn one" in result.text


def test_recall_excludes_the_active_chat_from_its_own_cross_chat_search(vault):
    # The active chat is persisted for real (not just held in memory) so it's
    # discoverable via vault.list_chats() -- the exclusion filter has to
    # actually find and skip it, this isn't just "nothing else exists yet."
    current = _vault_chat_with_two_turns(vault, "Current chat", "only turn a", "only turn b")
    from prisma.agents.session_orchestrator import SessionOrchestrator
    graph = SessionOrchestrator(system_prompt="sys", max_history_tokens=16000).graph_for(current.messages)
    chroma = MagicMock()
    chroma.embed_texts.return_value = [[1.0]] * 3  # query + the 2 in-chat candidates only
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=4000, chat_slug=current.slug)

    # If exclusion failed, the active chat would also surface via the
    # cross-chat path, tagged with its own slug instead of None -- and its
    # 2 turns would appear twice (once None, once self-tagged).
    assert all(item["chat_slug"] != current.slug for item in result.raw)
    node_ids = [item["node_id"] for item in result.raw]
    assert len(node_ids) == len(set(node_ids))


def test_recall_caps_number_of_other_chats_searched(vault):
    from prisma.services.chat_tools import _RECALL_CROSS_CHAT_LIMIT

    graph, current = _graph_with_two_turns("current a", "current b")
    for i in range(_RECALL_CROSS_CHAT_LIMIT + 3):
        _vault_chat_with_two_turns(vault, f"Other {i}", f"other {i} turn a", f"other {i} turn b")
    chroma = MagicMock()
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    def _fake_embed(texts, **kwargs):
        return [[1.0]] * len(texts)
    chroma.embed_texts.side_effect = _fake_embed

    toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=100_000, chat_slug=current.slug)

    texts_embedded = chroma.embed_texts.call_args[0][0]
    # query (1) + current chat's own 2 nodes + at most _RECALL_CROSS_CHAT_LIMIT other chats' 2 nodes each
    assert len(texts_embedded) <= 1 + 2 + _RECALL_CROSS_CHAT_LIMIT * 2


def test_recall_applies_cross_chat_discount(vault):
    graph, current = _graph_with_two_turns("current relevant", "current irrelevant")
    _vault_chat_with_two_turns(vault, "Other chat", "other more relevant", "other irrelevant")
    chroma = MagicMock()
    # Order: [query, current_relevant, current_irrelevant, other_more_relevant, other_irrelevant]
    # current_relevant: raw cosine 0.6. other_more_relevant: raw cosine 0.8,
    # but *0.7 discount -> 0.56 < 0.6 -- the in-chat candidate must still win.
    chroma.embed_texts.return_value = [
        [1.0, 0.0], [0.6, 0.8], [0.0, 1.0], [0.8, 0.6], [0.0, 1.0],
    ]
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=4000, chat_slug=current.slug)

    assert result.text.index("current relevant") < result.text.index("other more relevant")


def test_recall_degrade_path_drops_cross_chat_candidates(vault):
    graph, current = _graph_with_two_turns("current a", "current b")
    _vault_chat_with_two_turns(vault, "Other chat", "other a", "other b")
    chroma = MagicMock()
    chroma.embed_texts.return_value = None  # lease denied / embed failed
    toolbox = ChatToolbox(chroma, MagicMock(), vault)

    result = toolbox.call("RECALL", "anything", session_graph=graph, remaining_budget=4000, chat_slug=current.slug)

    assert "other a" not in result.text
    assert "other b" not in result.text
    assert all(item["chat_slug"] is None for item in result.raw)


def test_call_unknown_marker_raises():
    toolbox = ChatToolbox(MagicMock(), MagicMock(), MagicMock())
    with pytest.raises(ValueError):
        toolbox.call("NOT_A_TOOL", "x")
