"""Pure session-graph construction (ADR-019, docs/concepts/chat-session-graph.md)
-- split out from session_orchestrator.py so chat_tools.py's RECALL can build
a graph for a chat OTHER than the active one (cross-chat RECALL) without a
circular import: session_orchestrator.py already imports from chat_tools.py
for the system-prompt helpers, so chat_tools.py can't import graph
construction back out of session_orchestrator.py. This module has no
dependency on either, and both import from here instead.
"""
from __future__ import annotations

import networkx as nx

from prisma.storage.models.vault_models import TurnNode


def build_session_graph(messages: list[TurnNode]) -> nx.MultiDiGraph:
    """Main line (`NEXT`) from `messages`' order (typically a `Chat`'s own
    `messages`); each turn's own `tool_calls`/`thoughts`/`claims` as branch
    nodes off it (`INVOKES`/`REASONS`/`ASSERTS`); `alternates` as
    `REGENERATES` branches. Alternates' own nested tool_calls/thoughts/claims
    are not recursively expanded -- an intentional scope limit, not an
    oversight, since a superseded attempt's own branches are rarely what
    `RECALL` needs to reach."""
    g = nx.MultiDiGraph()
    prev_id: str | None = None
    for turn in messages:
        _add_turn(g, turn, prev_id)
        prev_id = turn.id
    return g


def _add_turn(g: nx.MultiDiGraph, turn: TurnNode, prev_id: str | None) -> None:
    g.add_node(turn.id, kind="turn", data=turn)
    if prev_id is not None:
        g.add_edge(prev_id, turn.id, kind="NEXT")
    for tc in turn.tool_calls:
        g.add_node(tc.id, kind="tool_call", data=tc)
        g.add_edge(turn.id, tc.id, kind="INVOKES")
    for th in turn.thoughts:
        g.add_node(th.id, kind="thought", data=th)
        g.add_edge(turn.id, th.id, kind="REASONS")
        if th.revises:
            g.add_edge(th.id, th.revises, kind="REVISES")
        if th.branches_from:
            g.add_edge(th.id, th.branches_from, kind="BRANCHES_FROM")
    for claim in turn.claims:
        g.add_node(claim.id, kind="claim", data=claim)
        g.add_edge(turn.id, claim.id, kind="ASSERTS")
    for alt in turn.alternates:
        g.add_node(alt.id, kind="turn", data=alt)
        g.add_edge(turn.id, alt.id, kind="REGENERATES")
