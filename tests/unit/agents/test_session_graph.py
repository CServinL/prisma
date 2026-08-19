"""Unit tests for build_session_graph() (docs/concepts/chat-session-graph.md)
-- the NEXT/INVOKES/REASONS/ASSERTS/REGENERATES edges plus the v3 additions
(WARRANTS/REBUTS/PRODUCES/ATTACHES)."""
from prisma.agents.session_graph import build_session_graph
from prisma.schema_gov import RichContent
from prisma.storage.models.vault_models import (
    AssetMediaNode, ChatRole, CitedClaimNode, InlineMediaNode, MediaKind, ToolCallNode, TurnNode,
    WarrantNode,
)


def _turn(role=ChatRole.user, text="hi", **kwargs) -> TurnNode:
    return TurnNode(role=role, content=RichContent(value=text), **kwargs)


def test_next_edge_connects_turns_in_order():
    a, b = _turn(text="hi"), _turn(role=ChatRole.assistant, text="hello")
    g = build_session_graph([a, b])
    assert g.has_edge(a.id, b.id)
    assert g[a.id][b.id][0]["kind"] == "NEXT"


def test_invokes_edge_for_tool_calls():
    turn = _turn(role=ChatRole.assistant, tool_calls=[ToolCallNode(tool="search_vault", args={})])
    g = build_session_graph([turn])
    tc_id = turn.tool_calls[0].id
    assert g.has_edge(turn.id, tc_id)
    assert g[turn.id][tc_id][0]["kind"] == "INVOKES"


def test_asserts_edge_for_claims():
    claim = CitedClaimNode(index=1, claim_text="x", sources=["s"], relation="citation")
    turn = _turn(role=ChatRole.assistant, claims=[claim])
    g = build_session_graph([turn])
    assert g[turn.id][claim.id][0]["kind"] == "ASSERTS"


def test_warrants_edge_for_a_claims_warrant():
    warrant = WarrantNode(text="because X implies Y", backing=["s2"])
    claim = CitedClaimNode(index=1, claim_text="x", sources=["s"], relation="citation", warrant=warrant)
    turn = _turn(role=ChatRole.assistant, claims=[claim])
    g = build_session_graph([turn])
    assert g.nodes[warrant.id]["kind"] == "warrant"
    assert g[claim.id][warrant.id][0]["kind"] == "WARRANTS"


def test_no_warrants_edge_when_claim_has_no_warrant():
    claim = CitedClaimNode(index=1, claim_text="x", sources=["s"], relation="citation")
    turn = _turn(role=ChatRole.assistant, claims=[claim])
    g = build_session_graph([turn])
    assert g.out_degree(claim.id) == 0


def test_rebuts_edge_points_at_another_claims_id():
    original = CitedClaimNode(index=1, claim_text="x is universal", sources=["s"], relation="citation")
    turn1 = _turn(role=ChatRole.assistant, claims=[original])
    exception = CitedClaimNode(
        index=1, claim_text="except under Z", sources=["s2"], relation="citation", rebuts=original.id,
    )
    turn2 = _turn(role=ChatRole.assistant, claims=[exception])
    g = build_session_graph([turn1, turn2])
    assert g.has_edge(exception.id, original.id)
    assert g[exception.id][original.id][0]["kind"] == "REBUTS"


def test_produces_edge_for_assistant_media():
    media = InlineMediaNode(kind=MediaKind.svg, value="<svg></svg>")
    turn = _turn(role=ChatRole.assistant, media=[media])
    g = build_session_graph([turn])
    assert g.nodes[media.id]["kind"] == "media"
    assert g[turn.id][media.id][0]["kind"] == "PRODUCES"


def test_attaches_edge_for_human_attachments():
    media = AssetMediaNode(kind=MediaKind.jpg, asset_path="chats/x/fig.jpg")
    turn = _turn(role=ChatRole.user, attachments=[media])
    g = build_session_graph([turn])
    assert g[turn.id][media.id][0]["kind"] == "ATTACHES"


def test_attached_slugs_are_not_added_to_the_graph():
    # Deliberate -- attached_slugs points into the vault, outside this
    # session's own structure, same as CITES/sources never being graph
    # edges either. Resolved as plain reference data, not a graph node.
    turn = _turn(role=ChatRole.user, attached_slugs=["some-note"])
    g = build_session_graph([turn])
    assert "some-note" not in g.nodes
    assert g.out_degree(turn.id) == 0
