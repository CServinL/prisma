"""prisma — chat session graph data model (ER diagram).

Run: .venv/bin/python docs/diagrams/08_chat_session_graph.py

Shows the internal structure of a single Chat's `messages` (ADR-019 v2 +
v3): TurnNode as the main line, with tool calls, reasoning, claims,
media, and regeneration attempts branching off each turn rather than
sharing its position in the list. See docs/concepts/chat-session-graph.md
for the full node/edge taxonomy this diagram mirrors — that page is the
source of truth; this is its structural picture.

Deliberately NOT shown as edges here: NEXT/REGENERATES/RECALLS
(TurnNode -> TurnNode) and REVISES/BRANCHES_FROM (ThinkingNode ->
ThinkingNode) and REBUTS (CitedClaimNode -> CitedClaimNode) are all
self-referencing relationships. sysatlas's ER ontology has no guard
against self-loops the way its architecture ontology does
(`_ontology/architecture.py`'s `_no_self_loop` validator) -- an earlier
version of this script with those five self-relate() calls hung the
renderer (observed: 11GB+ RSS, still climbing, killed after ~3 minutes).
Reported as a real sysatlas gap, not routed around silently: self-
referencing entities are common enough (linked lists, org charts,
category trees) that ERMap should either support them or reject them
loudly, the way SystemMap already does. These five relationships are
plain prose facts instead (main-line order, alternates, cross-references)
-- the branch structure below is what this diagram actually needs to show.
"""
from pathlib import Path
from sysatlas import ERMap

OUT = Path(__file__).with_suffix(".html")

m = ERMap(title="prisma — chat session graph")

# Main line
m.entity("TurnNode", label="TurnNode")
m.attribute("TurnNode", "id",        type="str", is_key=True, is_required=True)
m.attribute("TurnNode", "role",      type="user|assistant",   is_required=True)
m.attribute("TurnNode", "content",   type="RichContent",      is_required=True)
m.attribute("TurnNode", "model",     type="str")
m.attribute("TurnNode", "attached_slugs", type="str[]")

# Branches
m.entity("ToolCallNode", label="ToolCallNode")
m.attribute("ToolCallNode", "id",     type="str", is_key=True, is_required=True)
m.attribute("ToolCallNode", "tool",   type="str",               is_required=True)
m.attribute("ToolCallNode", "args",   type="JSON")
m.attribute("ToolCallNode", "result", type="str")
m.attribute("ToolCallNode", "status", type="ok|error")

m.entity("ThinkingNode", label="ThinkingNode")
m.attribute("ThinkingNode", "id",             type="str", is_key=True, is_required=True)
m.attribute("ThinkingNode", "thought",        type="str",               is_required=True)
m.attribute("ThinkingNode", "thought_number", type="int",               is_required=True)

m.entity("CitedClaimNode", label="CitedClaimNode")
m.attribute("CitedClaimNode", "id",                   type="str", is_key=True, is_required=True)
m.attribute("CitedClaimNode", "index",                type="int",               is_required=True)
m.attribute("CitedClaimNode", "sources",              type="str[]")
m.attribute("CitedClaimNode", "relation",             type="citation|attribution|relational")
m.attribute("CitedClaimNode", "faithfulness_checked", type="bool")
m.attribute("CitedClaimNode", "qualifier",            type="Qualifier")

m.entity("InferenceNode", label="InferenceNode")
m.attribute("InferenceNode", "id",        type="str", is_key=True, is_required=True)
m.attribute("InferenceNode", "index",     type="int",               is_required=True)
m.attribute("InferenceNode", "qualifier", type="Qualifier")

m.entity("WarrantNode", label="WarrantNode")
m.attribute("WarrantNode", "id",      type="str", is_key=True, is_required=True)
m.attribute("WarrantNode", "text",    type="str",               is_required=True)
m.attribute("WarrantNode", "backing", type="str[]")

m.entity("InlineMediaNode", label="InlineMediaNode")
m.attribute("InlineMediaNode", "id",      type="str", is_key=True, is_required=True)
m.attribute("InlineMediaNode", "kind",    type="svg|latex|drawio",  is_required=True)
m.attribute("InlineMediaNode", "value",   type="str",               is_required=True)

m.entity("AssetMediaNode", label="AssetMediaNode")
m.attribute("AssetMediaNode", "id",         type="str", is_key=True, is_required=True)
m.attribute("AssetMediaNode", "kind",       type="jpg|pdf",           is_required=True)
m.attribute("AssetMediaNode", "asset_path", type="str",               is_required=True)

# Vault-side target of CITES/PINNED_IN/attached_slugs -- not part of the
# session graph itself, shown as the boundary this structure points across.
m.entity("VaultNode", label="Note / Source / Chat (vault-wide)")
m.attribute("VaultNode", "slug", type="str", is_key=True, is_required=True)

# Edges (see chat-session-graph.md's Edge types table for the full mapping).
# NEXT/REGENERATES/RECALLS/REVISES/BRANCHES_FROM/REBUTS omitted -- all six
# are self-referencing, see the module docstring for why.
m.relate("TurnNode",       "ToolCallNode",     "INVOKES",              source_card="1", target_card="*")
m.relate("TurnNode",       "ThinkingNode",     "REASONS",              source_card="1", target_card="*")
m.relate("TurnNode",       "CitedClaimNode",   "ASSERTS",              source_card="1", target_card="*")
m.relate("TurnNode",       "InferenceNode",    "ASSERTS",              source_card="1", target_card="*")
m.relate("CitedClaimNode", "WarrantNode",      "WARRANTS",             source_card="0..1", target_card="1")
m.relate("InferenceNode",  "WarrantNode",      "WARRANTS",             source_card="0..1", target_card="1")
m.relate("TurnNode",       "InlineMediaNode",  "PRODUCES / ATTACHES",  source_card="1", target_card="*")
m.relate("TurnNode",       "AssetMediaNode",   "PRODUCES / ATTACHES",  source_card="1", target_card="*")
m.relate("CitedClaimNode", "VaultNode",        "CITES",                source_card="*", target_card="1")
m.relate("TurnNode",       "VaultNode",        "PINNED_IN (Excerpt) / attached_slugs", source_card="*", target_card="1")

m.save(str(OUT))
print(f"[sysatlas] wrote {OUT}")
