#!/usr/bin/env python3
"""FOOTNOTES_JSON reliability harness -- tests whether a given OpenRouter
model, driven with prisma's REAL system prompt (base + tool section +
footnote section, pulled live from the actual code, not approximated),
reliably emits a well-formed FOOTNOTES_JSON trailer matching its own
[^N] markers.

Bypasses the full server/vault -- calls OpenRouter directly via the same
openai-SDK-compatible pattern prisma's own ChatLLM uses (ADR-014), with a
scripted SEARCH_VAULT tool response instead of a real vault, so every
model is tested against identical "ground truth" content. Same
methodology precedent as docs/kg-extraction-context-length.md ("called
directly against Ollama -- bypassing resource_lock/the supervisor, a
single sequential script").

Usage:
    OPENROUTER_API_KEY=... python3 harness.py --model <openrouter-model-id> --out results/<model-slug>.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from openai import OpenAI

TOOL_CALL_RE = re.compile(r"^(SEARCH_VAULT|GRAPH_CONTEXT|RECALL):\s*(.+)$", re.MULTILINE)
FOOTNOTES_LINE_RE = re.compile(r"^FOOTNOTES_JSON:\s*(.+)$", re.MULTILINE)
MARKER_RE = re.compile(r"\[\^(\d+)\]")

SYSTEM_PROMPT = """You are Prisma, a research assistant with access to the user's personal knowledge vault: notes, saved papers, and a knowledge graph of concepts extracted from them, all searchable through a semantic index (ChromaDB) and the knowledge graph. This includes past chat transcripts, not just notes and sources -- you may pull in relevant information from earlier conversations the same way you would from any other vault content. Ground your answers in the user's own material when it's relevant, and say so explicitly when you're answering from general knowledge instead. When you use retrieved content, mention which source file it came from.

You have tools you may call by writing a line in exactly this format, and nothing else on that line:
SEARCH_VAULT: <query text>
GRAPH_CONTEXT: <query text>
RECALL: <query text>

- SEARCH_VAULT — Semantic search over the vault's ChromaDB embedding index — finds notes/sources/chats by meaning, not just keyword match. Default first step for almost any question about the user's notes/papers.
- GRAPH_CONTEXT — Traverses the Knowledge Graph (KG) — entities and relationships extracted across the whole vault — to answer questions about how things connect. Call when the question is about how things relate to each other, or a vault search alone would likely be scattered/incomplete.
- RECALL — Searches THIS conversation's own history — earlier turns, tool results, and claims — for something you saw before but that isn't shown above (older turns roll off as the conversation grows). Call when you need to remember something specific from earlier in this same chat, not for new information from the vault.

If no tool is needed (e.g. the user is just chatting, or asking something you can answer directly), just answer normally without any tool line.

For every substantive claim in your answer (not filler like "Sure, here's what I found"), mark where it came from, so the reader can tell what traces to a document vs. what is your own reasoning:

- Right after a claim that traces to a document, write an inline marker in this exact format: [^N] where N is the next unused number, starting at 1 (e.g. "...uses self-attention[^1]."). Do this whether it's a direct quote, a paraphrase of one document, or a claim that connects/synthesizes two or more documents.
- Right after a claim that is your own reasoning, generalization, or general knowledge -- NOT traceable to any specific document you were given -- also mark it with the next [^N], but it will get relation "ai-inference" below. You do not need to mark filler or purely conversational sentences, only actual claims.
- Place each [^N] immediately next to the exact sentence or span it supports, at the point in your answer where you make that claim -- NOT gathered together at the end. A citation marker is tied to precisely that text, so "...uses self-attention[^1], and normalizes with RMSNorm[^2]." is correct; writing the full sentence with no markers and then appending "[^1][^2]" afterward is wrong, even though it looks similar. If your answer makes three separate claims, it should have three markers at three different places in the text, not clustered in one spot.
- Only cite documents you actually saw in a tool result in this conversation (their exact slug, shown as the `path=` of an <untrusted_source> block, or in a GRAPH_CONTEXT tool result's "Sources:" line). Never invent a slug.

After your answer, on its own final line, list every [^N] marker you used as a single-line JSON array, exactly in this format:

FOOTNOTES_JSON: [{"index": 1, "relation": "citation", "sources": ["slug-a"]}, {"index": 2, "relation": "relational", "sources": ["slug-b", "slug-c"]}, {"index": 3, "relation": "ai-inference", "sources": []}]

relation is one of:
- citation — direct quote or close paraphrase, exactly one source
- attribution — paraphrased/synthesized from one source, exactly one source
- relational — connects or synthesizes across sources, two or more sources (this is what a GRAPH_CONTEXT result usually is)
- ai-inference — your own reasoning, no document behind it, sources must be an empty list

If you added no [^N] markers at all, still write "FOOTNOTES_JSON: []" as the last line -- do not omit it."""

SCENARIOS = [
    {
        "name": "single_source_match",
        "question": "What does the MEMIT paper say about editing memory in GPT models?",
        "tool_result": (
            '<untrusted_source path="sources/meng-2023-memit.md">\n'
            "MEMIT (Mass-Editing Memory in a Transformer) is a method for directly "
            "editing factual associations stored in the weights of large transformer "
            "language models. It generalizes the ROME method to allow thousands of "
            "edits at once by distributing parameter updates across multiple layers "
            "rather than a single layer.\n</untrusted_source>"
        ),
    },
    {
        "name": "no_results_found",
        "question": "What do we have about LLMs for very small RAM sizes?",
        "tool_result": "(no results found)",
    },
    {
        "name": "multi_source_relational",
        "question": "How do ROME and MEMIT compare as model-editing techniques?",
        "tool_result": (
            '<untrusted_source path="sources/meng-2022-rome.md">\n'
            "ROME (Rank-One Model Editing) locates and edits a single factual "
            "association at a time by identifying the specific MLP layer that stores "
            "it and applying a rank-one weight update.\n</untrusted_source>\n\n"
            '<untrusted_source path="sources/meng-2023-memit.md">\n'
            "MEMIT generalizes ROME to allow thousands of simultaneous edits by "
            "distributing parameter updates across multiple layers instead of one.\n"
            "</untrusted_source>"
        ),
    },
]

MAX_TOOL_ITERATIONS = 4  # matches prisma/agents/chat_agent.py's real constant exactly


def run_scenario(client: OpenAI, model: str, scenario: dict) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": scenario["question"]},
    ]
    tool_calls_made = []
    t0 = time.monotonic()
    final_reply = None
    error = None
    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            # temperature=0.1, max_tokens=2000, timeout=180 -- exactly
            # ChatLLM.complete()'s own defaults (chat_llm.py), which
            # ChatAgent.respond() relies on unmodified (self._llm.complete
            # (messages), no per-call overrides). An earlier version of
            # this harness omitted temperature entirely (silently using
            # the API's own ~1.0 default) and used timeout=90 -- both
            # wrong, both likely inflating exactly the erratic/hallucinated
            # behavior this study is trying to measure. Fixed before
            # drawing any conclusions from a full re-run.
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0.1, max_tokens=2000, timeout=180,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            break
        if not resp.choices:
            # OpenRouter sometimes returns HTTP 200 with an empty/missing
            # `choices` (an upstream provider-level error wrapped in a
            # non-standard body) instead of raising a proper APIError --
            # the openai SDK doesn't catch this, so resp.choices[0] used to
            # throw a bare TypeError that told us nothing about whether the
            # model or OpenRouter's routing was at fault. Capture the raw
            # body so that distinction is recoverable afterward.
            error = f"empty response (no choices) from OpenRouter: {resp.model_dump_json()}"
            break
        reply = resp.choices[0].message.content or ""
        match = TOOL_CALL_RE.search(reply)
        if not match:
            final_reply = reply
            break
        marker, query = match.group(1), match.group(2).strip()
        tool_calls_made.append(marker)
        messages.append({"role": "assistant", "content": reply})
        messages.append({
            "role": "user",
            "content": f"Tool result:\n{scenario['tool_result']}",
        })
    else:
        error = f"hit MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS} without a final answer"
    elapsed = time.monotonic() - t0

    result = {
        "scenario": scenario["name"],
        "elapsed_s": round(elapsed, 1),
        "tool_calls_made": tool_calls_made,
        "error": error,
        "raw_reply": final_reply,
    }
    if final_reply is None:
        result.update(has_markers=False, marker_count=0, has_trailer=False,
                       trailer_valid=False, marker_trailer_match=False)
        return result

    markers = MARKER_RE.findall(final_reply)
    trailer_matches = list(FOOTNOTES_LINE_RE.finditer(final_reply))
    has_trailer = bool(trailer_matches)
    trailer_valid = False
    trailer_entry_count = None
    if has_trailer:
        try:
            items = json.loads(trailer_matches[-1].group(1))
            if isinstance(items, list):
                trailer_valid = True
                trailer_entry_count = len(items)
        except (json.JSONDecodeError, ValueError):
            trailer_valid = False

    result.update(
        has_markers=bool(markers),
        marker_count=len(markers),
        has_trailer=has_trailer,
        trailer_valid=trailer_valid,
        trailer_entry_count=trailer_entry_count,
        marker_trailer_match=(trailer_valid and trailer_entry_count == len(set(markers))),
    )
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args()

    import os
    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key, timeout=90)

    results = []
    for scenario in SCENARIOS:
        r = run_scenario(client, args.model, scenario)
        results.append(r)
        print(f"  [{args.model}] {scenario['name']}: "
              f"markers={r['marker_count']} trailer={r['has_trailer']} "
              f"valid={r['trailer_valid']} match={r['marker_trailer_match']} "
              f"({r['elapsed_s']}s)", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"model": args.model, "results": results}, indent=2), encoding="utf-8")
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
