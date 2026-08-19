"""Unit tests for Chat/TurnNode (ADR-019 + the session-graph schema v2) --
the pure-JSON .sess format, node types, versioning (schema_gov.VersionedModel),
the 2026-08-04 alternates decision, and the v1->v2 migration."""
from pathlib import Path

from prisma.schema_gov import ContentFormat, RichContent
from prisma.storage.models.vault_models import (
    CHAT_SCHEMA_VERSION, AssetMediaNode, Chat, ChatRole, CitedClaimNode, InferenceNode,
    InlineMediaNode, MediaKind, NodeType, Qualifier, ThinkingNode, ToolCallNode, TurnNode,
    WarrantNode,
)


def _chat(**overrides) -> Chat:
    defaults = dict(slug="test-chat", title="Test Chat", path=Path("/tmp/test-chat.sess"))
    defaults.update(overrides)
    return Chat(**defaults)


def test_new_chat_gets_current_schema_version():
    c = _chat()
    assert c.schema_version == CHAT_SCHEMA_VERSION


def test_node_type_defaults_to_chat():
    assert _chat().node_type == NodeType.chat


def test_turn_node_content_is_rich_content():
    msg = TurnNode(role=ChatRole.assistant, content=RichContent(value="hello"))
    assert msg.content.format == ContentFormat.markdown
    assert msg.content.value == "hello"


def test_turn_node_gets_a_stable_id():
    a, b = TurnNode(role=ChatRole.user, content=RichContent(value="hi")), TurnNode(role=ChatRole.user, content=RichContent(value="hi"))
    assert a.id and b.id and a.id != b.id


def test_round_trip_through_json_preserves_messages_claims_and_model():
    c = _chat(
        messages=[
            TurnNode(role=ChatRole.user, content=RichContent(value="hi")),
            TurnNode(
                role=ChatRole.assistant,
                content=RichContent(value="answer[^1]"),
                model="qwen2.5-3b",
                claims=[CitedClaimNode(index=1, claim_text="answer", sources=["src-a"], relation="citation")],
                tool_calls=[ToolCallNode(tool="search_vault", args={"query": "x"}, result="hit text")],
            ),
        ],
    )
    restored = Chat.model_validate_json(c.model_dump_json())
    assert len(restored.messages) == 2
    assert restored.messages[1].model == "qwen2.5-3b"
    assert restored.messages[1].content.value == "answer[^1]"
    assert restored.messages[1].claims[0].sources == ["src-a"]
    assert restored.messages[1].tool_calls[0].tool == "search_vault"
    assert restored.messages[1].tool_calls[0].result == "hit text"


def test_claims_discriminated_union_round_trips_both_kinds():
    msg = TurnNode(
        role=ChatRole.assistant, content=RichContent(value="a[^1] b[^2]"),
        claims=[
            CitedClaimNode(index=1, claim_text="a", sources=["s"], relation="citation"),
            InferenceNode(index=2, claim_text="b"),
        ],
    )
    restored = TurnNode.model_validate_json(msg.model_dump_json())
    assert isinstance(restored.claims[0], CitedClaimNode)
    assert isinstance(restored.claims[1], InferenceNode)
    assert restored.claims[1].claim_text == "b"


def test_thinking_node_revises_and_branches_from_reference_by_id():
    first = ThinkingNode(thought="initial idea", thought_number=1)
    revision = ThinkingNode(thought="better idea", thought_number=2, revises=first.id)
    branch = ThinkingNode(thought="alternate path", thought_number=3, branches_from=first.id)
    assert revision.revises == first.id
    assert branch.branches_from == first.id


def test_alternates_preserve_prior_regeneration_attempts():
    old_attempt = TurnNode(role=ChatRole.assistant, content=RichContent(value="v1 answer"), model="qwen2.5-3b")
    live = TurnNode(
        role=ChatRole.assistant, content=RichContent(value="v2 answer"), model="qwen2.5-7b",
        alternates=[old_attempt],
    )
    restored = TurnNode.model_validate_json(live.model_dump_json())
    assert restored.content.value == "v2 answer"
    assert restored.model == "qwen2.5-7b"
    assert len(restored.alternates) == 1
    assert restored.alternates[0].content.value == "v1 answer"
    assert restored.alternates[0].model == "qwen2.5-3b"


def test_absent_schema_version_in_raw_json_is_treated_as_v1_and_migrated():
    # A hand-constructed or otherwise pre-versioning raw dict must still load.
    raw = {"slug": "x", "title": "X", "path": "/tmp/x.sess"}
    c = Chat.model_validate(raw)
    assert c.schema_version == CHAT_SCHEMA_VERSION


# ── v1 -> v2 migration ────────────────────────────────────────────────────

def _v1_chat_raw(**overrides) -> dict:
    defaults = dict(slug="x", title="X", path="/tmp/x.sess", schema_version=1)
    defaults.update(overrides)
    return defaults


def test_v1_message_migrates_to_turn_node():
    raw = _v1_chat_raw(messages=[
        {"role": "user", "content": {"format": "md", "value": "hi"}, "timestamp": "2026-08-01T00:00:00"},
    ])
    c = Chat.model_validate(raw)
    assert c.schema_version == CHAT_SCHEMA_VERSION
    assert isinstance(c.messages[0], TurnNode)
    assert c.messages[0].content.value == "hi"


def test_v1_footnote_citation_migrates_to_cited_claim_node():
    raw = _v1_chat_raw(messages=[{
        "role": "assistant", "content": {"format": "md", "value": "answer[^1]"},
        "timestamp": "2026-08-01T00:00:00", "model": "qwen",
        "footnotes": [{"index": 1, "relation": "citation", "sources": ["src-a"], "claim_text": "answer", "faithfulness_checked": True}],
    }])
    c = Chat.model_validate(raw)
    claim = c.messages[0].claims[0]
    assert isinstance(claim, CitedClaimNode)
    assert claim.index == 1
    assert claim.sources == ["src-a"]
    assert claim.faithfulness_checked is True


def test_v1_footnote_ai_inference_migrates_to_inference_node():
    raw = _v1_chat_raw(messages=[{
        "role": "assistant", "content": {"format": "md", "value": "opinion[^1]"},
        "timestamp": "2026-08-01T00:00:00",
        "footnotes": [{"index": 1, "relation": "ai-inference", "sources": [], "claim_text": "opinion"}],
    }])
    c = Chat.model_validate(raw)
    claim = c.messages[0].claims[0]
    assert isinstance(claim, InferenceNode)
    assert claim.index == 1


def test_v1_tool_call_migrates_with_no_result():
    raw = _v1_chat_raw(messages=[{
        "role": "assistant", "content": {"format": "md", "value": "answer"},
        "timestamp": "2026-08-01T00:00:00",
        "tool_calls": [{"tool": "search_vault", "args": {"query": "x"}}],
    }])
    c = Chat.model_validate(raw)
    tc = c.messages[0].tool_calls[0]
    assert tc.tool == "search_vault"
    assert tc.result is None  # v1 never persisted results -- absent, not fabricated


def test_v1_alternates_migrate_recursively():
    raw = _v1_chat_raw(messages=[{
        "role": "assistant", "content": {"format": "md", "value": "v2"},
        "timestamp": "2026-08-01T00:00:00", "model": "qwen2.5-7b",
        "alternates": [{
            "role": "assistant", "content": {"format": "md", "value": "v1"},
            "timestamp": "2026-08-01T00:00:00", "model": "qwen2.5-3b",
        }],
    }])
    c = Chat.model_validate(raw)
    alt = c.messages[0].alternates[0]
    assert isinstance(alt, TurnNode)
    assert alt.content.value == "v1"
    assert alt.model == "qwen2.5-3b"


def test_v1_chat_with_no_messages_migrates_cleanly():
    raw = _v1_chat_raw()
    c = Chat.model_validate(raw)
    assert c.messages == []


# ── v3: Toulmin extension, MediaNode, attachments ──────────────────────────

def test_warrant_and_qualifier_round_trip_on_a_cited_claim():
    claim = CitedClaimNode(
        index=1, claim_text="X causes Y", sources=["src-a"], relation="citation",
        qualifier=Qualifier.probable,
        warrant=WarrantNode(text="src-a's methodology directly measures causation", backing=["src-b"]),
    )
    restored = CitedClaimNode.model_validate_json(claim.model_dump_json())
    assert restored.qualifier == Qualifier.probable
    assert restored.warrant.text == "src-a's methodology directly measures causation"
    assert restored.warrant.backing == ["src-b"]


def test_rebuts_references_another_claim_by_id():
    original = CitedClaimNode(index=1, claim_text="X is universal", sources=["src-a"], relation="citation")
    exception = CitedClaimNode(
        index=2, claim_text="X fails under condition Z", sources=["src-c"], relation="citation",
        rebuts=original.id,
    )
    assert exception.rebuts == original.id


def test_inference_node_also_carries_qualifier_and_warrant():
    inf = InferenceNode(index=1, claim_text="probably related", qualifier=Qualifier.tentative)
    restored = InferenceNode.model_validate_json(inf.model_dump_json())
    assert restored.qualifier == Qualifier.tentative
    assert restored.warrant is None


def test_inline_media_node_kinds():
    svg = InlineMediaNode(kind=MediaKind.svg, value="<svg></svg>")
    latex = InlineMediaNode(kind=MediaKind.latex, value=r"$E=mc^2$")
    drawio = InlineMediaNode(kind=MediaKind.drawio, value="<mxGraphModel/>")
    assert svg.value == "<svg></svg>"
    assert latex.value == r"$E=mc^2$"
    assert drawio.kind == MediaKind.drawio


def test_asset_media_node_uses_asset_path_not_inline_value():
    jpg = AssetMediaNode(kind=MediaKind.jpg, asset_path="chats/my-chat/figure-1.jpg", caption="Figure 1")
    assert jpg.kind == MediaKind.jpg
    assert jpg.asset_path == "chats/my-chat/figure-1.jpg"
    assert not hasattr(jpg, "value")  # genuinely a different shape, not a null field


def test_turn_node_media_is_assistant_output():
    turn = TurnNode(
        role=ChatRole.assistant, content=RichContent(value="here's a diagram"),
        media=[InlineMediaNode(kind=MediaKind.svg, value="<svg></svg>")],
    )
    restored = TurnNode.model_validate_json(turn.model_dump_json())
    assert len(restored.media) == 1
    assert isinstance(restored.media[0], InlineMediaNode)
    assert restored.media[0].kind == MediaKind.svg


def test_turn_node_media_discriminates_inline_vs_asset():
    turn = TurnNode(
        role=ChatRole.assistant, content=RichContent(value="figure + diagram"),
        media=[
            InlineMediaNode(kind=MediaKind.drawio, value="<mxGraphModel/>"),
            AssetMediaNode(kind=MediaKind.jpg, asset_path="chats/x/fig.jpg"),
        ],
    )
    restored = TurnNode.model_validate_json(turn.model_dump_json())
    assert isinstance(restored.media[0], InlineMediaNode)
    assert isinstance(restored.media[1], AssetMediaNode)


def test_turn_node_attachments_and_attached_slugs_are_human_input():
    turn = TurnNode(
        role=ChatRole.user, content=RichContent(value="check this diagram against my notes"),
        attachments=[InlineMediaNode(kind=MediaKind.drawio, value="<mxGraphModel/>")],
        attached_slugs=["my-existing-note"],
    )
    restored = TurnNode.model_validate_json(turn.model_dump_json())
    assert restored.attachments[0].kind == MediaKind.drawio
    assert restored.attached_slugs == ["my-existing-note"]


def test_new_turn_node_defaults_media_and_attachments_to_empty():
    turn = TurnNode(role=ChatRole.user, content=RichContent(value="hi"))
    assert turn.media == []
    assert turn.attachments == []
    assert turn.attached_slugs == []


# ── v2 -> v3 migration ──────────────────────────────────────────────────────

def _v2_chat_raw(**overrides) -> dict:
    defaults = dict(slug="x", title="X", path="/tmp/x.sess", schema_version=2)
    defaults.update(overrides)
    return defaults


def test_v2_chat_migrates_to_v3_with_empty_defaults():
    raw = _v2_chat_raw(messages=[{
        "role": "assistant", "content": {"format": "md", "value": "answer[^1]"},
        "timestamp": "2026-08-01T00:00:00",
        "claims": [{"kind": "claim", "index": 1, "claim_text": "answer", "sources": ["src-a"], "relation": "citation"}],
    }])
    c = Chat.model_validate(raw)
    assert c.schema_version == CHAT_SCHEMA_VERSION
    turn = c.messages[0]
    assert turn.media == [] and turn.attachments == [] and turn.attached_slugs == []
    claim = turn.claims[0]
    assert claim.qualifier is None
    assert claim.warrant is None
    assert claim.rebuts is None


# ── v3 -> v4 migration (relation's citation/paraphrase split) ───────────────

def _v3_chat_raw(**overrides) -> dict:
    defaults = dict(slug="x", title="X", path="/tmp/x.sess", schema_version=3)
    defaults.update(overrides)
    return defaults


def test_v3_chat_with_old_citation_relation_migrates_unchanged():
    # A pre-split "citation" is genuinely ambiguous (quote vs. paraphrase) --
    # the migration must not reinterpret it, just carry it forward as-is.
    raw = _v3_chat_raw(messages=[{
        "role": "assistant", "content": {"format": "md", "value": "answer[^1]"},
        "timestamp": "2026-08-01T00:00:00",
        "claims": [{"kind": "claim", "index": 1, "claim_text": "answer", "sources": ["src-a"], "relation": "citation"}],
    }])
    c = Chat.model_validate(raw)
    assert c.schema_version == CHAT_SCHEMA_VERSION
    assert c.messages[0].claims[0].relation == "citation"


def test_cited_claim_node_accepts_paraphrase_relation():
    claim = CitedClaimNode(index=1, claim_text="restated in different words", sources=["src-a"], relation="paraphrase")
    assert claim.relation == "paraphrase"
