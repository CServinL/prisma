"""Unit tests for KnowledgeGraphService — the native, Kùzu-backed knowledge
graph module that replaces the third-party `graphify` pip dependency.
See TODO.md and docs/wiki/adr/ADR-012-process-supervision.md.
"""
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from prisma.services.knowledge_graph_service import (
    Edge,
    Extraction,
    KnowledgeGraphService,
    Node,
    TOP_ENTITIES_CACHE_SIZE,
    _extraction_system_prompt,
    _KUZU_BUFFER_POOL_SIZE_BYTES,
    _sanitize_escape_sequences,
    _strip_dense_data_paragraphs,
    _strip_feature_catalog_paragraphs,
    _strip_reference_list_paragraphs,
)
from prisma.storage.models.kg_models import (
    AuthorSummary,
    GraphRelevance,
    OrphanEntity,
    SuggestedQuestion,
    SurprisingConnection,
    TopEntity,
    VaultHealthResponse,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def vault(tmp_path):
    from prisma.services.vault import VaultService
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


@pytest.fixture
def kg(vault, tmp_path):
    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out")
    service._ensure_connection()
    return service


def _extraction(nodes=None, edges=None) -> Extraction:
    return Extraction(
        nodes=[Node(**n) for n in (nodes or [])],
        edges=[Edge(**e) for e in (edges or [])],
    )


def _patch_create(kg, **kwargs):
    return patch.object(kg._instructor_client.chat.completions, "create", **kwargs)


# ── Kùzu buffer pool sizing ───────────────────────────────────────────────────
# Confirmed live 2026-08-28: kuzu.Database()'s own default (buffer_pool_size=0,
# left unset) is "~80% of system memory" -- read off /proc/meminfo, which
# inside a container reports the host node's total memory, not the
# container's actual cgroup limit. The kg worker held ~3GB RSS against a
# 35MB on-disk database as a result. Must always pass an explicit, bounded
# value instead of trusting Kùzu's own auto-sizing.

def test_ensure_connection_passes_a_bounded_buffer_pool_size(vault, tmp_path):
    import kuzu

    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out")
    # A spy, not a full mock -- _ensure_connection also runs real schema-
    # creation queries against the connection right after constructing the
    # Database, so this needs a genuine (tiny, tmp_path-backed) Kùzu
    # instance underneath, not a MagicMock standing in for query results.
    with patch("kuzu.Database", wraps=kuzu.Database) as spy_database:
        service._ensure_connection()

    spy_database.assert_called_once()
    assert spy_database.call_args.kwargs["buffer_pool_size"] == _KUZU_BUFFER_POOL_SIZE_BYTES
    assert _KUZU_BUFFER_POOL_SIZE_BYTES > 0


# ── configurable entity/relationship caps ─────────────────────────────────────
# Per-deployment, not a shared constant: a cloud-routed model (cheap per-token
# cost, no local-hardware speed concern) can afford a much higher cap than a
# local model — see _extraction_system_prompt's own docstring.

def test_extraction_system_prompt_default_caps():
    prompt = _extraction_system_prompt()
    assert "at most 15 of the most important entities" in prompt
    assert "at most 20 of the most important relationships" in prompt


def test_extraction_system_prompt_custom_caps():
    prompt = _extraction_system_prompt(max_entities=50, max_relationships=80)
    assert "at most 50 of the most important entities" in prompt
    assert "at most 80 of the most important relationships" in prompt


def test_extraction_system_prompt_preserves_literal_node_id_braces():
    # {stem}_{entity} in the "Node ID format" section is literal instruction
    # text for the model, not an f-string interpolation — must survive
    # parameterizing the entity/relationship caps without becoming a
    # NameError or getting silently swallowed.
    prompt = _extraction_system_prompt()
    assert "{stem}_{entity}" in prompt


def test_service_uses_configured_caps_in_its_system_prompt(vault, tmp_path):
    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out", max_entities=3, max_relationships=5)
    assert "at most 3 of the most important entities" in service._extraction_system
    assert "at most 5 of the most important relationships" in service._extraction_system


# ── openrouter provider support ───────────────────────────────────────────────

def test_openrouter_base_url_not_double_suffixed(vault, tmp_path):
    # kg_app.py's _llm_base_url() delegates to LLMConfig.base_url, which for
    # openrouter already returns the complete ".../api/v1" — the client
    # construction must not append /v1 a second time (unlike the
    # ollama/llama_cpp case, where ollama_base_url is host-only).
    service = KnowledgeGraphService(
        vault, kg_dir=tmp_path / "kg-out",
        provider="openrouter", ollama_base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
    )
    assert str(service._instructor_client.client.base_url) == "https://openrouter.ai/api/v1/"


def test_ollama_base_url_still_gets_v1_appended(vault, tmp_path):
    service = KnowledgeGraphService(
        vault, kg_dir=tmp_path / "kg-out",
        provider="ollama", ollama_base_url="http://localhost:11434",
    )
    assert str(service._instructor_client.client.base_url) == "http://localhost:11434/v1/"


def test_context_window_override_skips_live_resolution(vault, tmp_path):
    service = KnowledgeGraphService(
        vault, kg_dir=tmp_path / "kg-out",
        provider="openrouter", ollama_base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test", context_window_override=128000,
    )
    # No network call should happen — already marked resolved at construction.
    assert service._context_window_resolved is True
    assert service._resolve_context_window() == 128000


def test_no_context_window_override_defaults_to_unresolved(vault, tmp_path):
    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out")
    assert service._context_window_resolved is False


# ── Escape-sequence sanitization ──────────────────────────────────────────────
# Confirmed live 2026-07-07 (docs/logs/kg-dead-letter-triage-2026-07-07.md): a real
# paper's appendix of raw byte-sequence descriptions (e.g. `Hebrew: "\xd6"?`)
# made the model try to preserve these sequences verbatim inside its JSON
# string output, producing malformed `\u` escapes that failed Pydantic
# validation across all 4 retries — every time, deterministically.

def test_sanitize_escape_sequences_strips_hex_and_unicode_escapes():
    text = 'Hebrew: "\\xd6"? and Arabic: unicode start "\\xd8" and Japanese: \\u0e98\\u3000'
    result = _sanitize_escape_sequences(text)
    assert "\\x" not in result
    assert "\\u" not in result
    assert "Hebrew" in result and "Arabic" in result and "Japanese" in result


def test_sanitize_escape_sequences_leaves_normal_prose_untouched():
    text = "MEMIT edits factual associations in GPT-J using a closed-form update."
    assert _sanitize_escape_sequences(text) == text


def test_extract_file_sanitizes_escape_sequences_before_calling_model(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text(
        '---\ntype: note\n---\nHebrew: "\\xd6"? and Arabic: unicode start "\\xd8"?',
        encoding="utf-8",
    )
    result = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    with _patch_create(kg, return_value=result) as mock_create, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    sent_prompt = mock_create.call_args.kwargs["messages"][1]["content"]
    assert "\\xd6" not in sent_prompt
    assert "\\xd8" not in sent_prompt


# ── Dense data-table stripping ─────────────────────────────────────────────────
# Confirmed live 2026-07-08 (docs/logs/kg-dead-letter-triage-2026-07-07.md follow-up):
# a real paper's flattened benchmark-score table (e.g. "hyperbaton 54.2 51.7
# movie_dialog_same_or_diff 54.5 50.7 ...") made the model try to enumerate
# every row as an entity, blowing past the output-budget instruction (64
# nodes/61 edges against a stated cap of 15/20) even though it no longer hit
# max_tokens. semchunk has no notion of table structure and each chunk is
# extracted with no memory of neighboring chunks, so stripping this content
# before chunking — rather than relying on the model to recognize and skip it
# per chunk — removes the failure mode at the source.

def test_strip_dense_data_paragraphs_removes_flattened_score_table():
    table = (
        "hyperbaton 54.2 51.7 movie_dialog_same_or_diff 54.5 50.7 "
        "causal_judgment 57.4 50.8 winowhy 62.5 56.7 formal_fallacies 52.1 50.7 "
        "movie_recommendation 75.6 50.5 crash_blossom 47.6 63.6"
    )
    text = f"Intro prose about the method.\n\n{table}\n\nMore prose after the table."
    result = _strip_dense_data_paragraphs(text)
    assert table not in result
    assert "Intro prose about the method." in result
    assert "More prose after the table." in result


def test_strip_dense_data_paragraphs_leaves_normal_prose_untouched():
    text = "MEMIT edits factual associations in GPT-J using a closed-form update."
    assert _strip_dense_data_paragraphs(text) == text


def test_strip_dense_data_paragraphs_leaves_short_paragraphs_with_numbers():
    text = "The model achieves 54.2% accuracy on this task."
    assert _strip_dense_data_paragraphs(text) == text


def test_extract_file_strips_dense_data_table_before_chunking(kg, vault):
    table = " ".join(f"task_{i} {i}.{i} {i}.{i+1}" for i in range(30))
    f = vault.root / "notes" / "test.md"
    f.write_text(f"---\ntype: note\n---\nIntro prose.\n\n{table}\n\nOutro prose.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    with _patch_create(kg, return_value=result) as mock_create, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    sent_prompt = mock_create.call_args.kwargs["messages"][1]["content"]
    assert "task_0" not in sent_prompt
    assert "Intro prose." in sent_prompt or "Outro prose." in sent_prompt


# ── Reference-list stripping ───────────────────────────────────────────────────
# Confirmed live 2026-07-08: two real survey papers (Huang 2024 hallucination
# survey, Liang 2022 multimodal ML survey) kept dead-lettering on max_tokens
# after the dense-data-table fix alone — their failing chunks were flattened
# bibliography entries ("[42] Author. Year. Title..."), not tables. PyMuPDF's
# PDF-to-text extraction has no blank-line separation between consecutive
# reference entries, so a paper's whole References section collapses into a
# few huge paragraphs each packed with many "[NN]"-style markers back to back.
# True bibliography paragraphs in both real papers had 13+ markers; ordinary
# lit-review prose citing several works in one paragraph never exceeded 11 in
# either paper — a clean, empirically-observed gap.

def test_strip_reference_list_paragraphs_removes_flattened_bibliography():
    refs = " ".join(f"[{i}] Some Author. 20{i:02d}. A Paper Title. Some Venue." for i in range(1, 15))
    text = f"Intro prose about the method.\n\n{refs}\n\nMore prose after the references."
    result = _strip_reference_list_paragraphs(text)
    assert refs not in result
    assert "Intro prose about the method." in result
    assert "More prose after the references." in result


def test_strip_reference_list_paragraphs_leaves_lit_review_prose_untouched():
    # 11 markers — same shape as a real false-positive risk (a survey's
    # literature-review paragraph citing several works in flowing prose),
    # one below the empirically-observed threshold.
    text = " ".join(f"Prior work [{i}] explores a related idea in this area." for i in range(1, 12))
    assert _strip_reference_list_paragraphs(text) == text


def test_strip_reference_list_paragraphs_leaves_normal_prose_untouched():
    text = "MEMIT edits factual associations in GPT-J using a closed-form update."
    assert _strip_reference_list_paragraphs(text) == text


def test_extract_file_strips_reference_list_before_chunking(kg, vault):
    refs = " ".join(f"[{i}] Some Author. 20{i:02d}. A Paper Title. Some Venue." for i in range(1, 15))
    f = vault.root / "notes" / "test.md"
    f.write_text(f"---\ntype: note\n---\nIntro prose.\n\n{refs}\n\nOutro prose.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    with _patch_create(kg, return_value=result) as mock_create, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    sent_prompt = mock_create.call_args.kwargs["messages"][1]["content"]
    assert "[1] Some Author" not in sent_prompt
    assert "Intro prose." in sent_prompt or "Outro prose." in sent_prompt


# ── Feature-catalog stripping ──────────────────────────────────────────────────
# Confirmed live 2026-07-08: Bricken 2023's "Towards Monosemanticity" appendix
# is an interactive per-neuron browser flattened to markdown as hundreds of
# repeating <feature ID> / <one-line description> / "Zoom to [View details]"
# triples. No single paragraph here looks dense or enumeration-shaped in
# isolation (unlike the data-table/reference-list cases) — the pattern only
# shows up across a run of paragraphs, so detection has to look at
# neighboring paragraphs, not one at a time.

def test_strip_feature_catalog_paragraphs_removes_entry_triples():
    text = (
        "Intro prose about the method.\n\n"
        "A/1/1538\n\n"
        "Citations in a [@author] or [@authoryear] format\n\n"
        "Zoom to [↗ View details](<https://transformer-circuits.pub/2023/monosemantic-features/vis/a1.html#feature-1538>)\n\n"
        "A/1/1875\n\n"
        "Markdown citation predicting a year\n\n"
        "Zoom to [↗ View details](<https://transformer-circuits.pub/2023/monosemantic-features/vis/a1.html#feature-1875>)\n\n"
        "More prose after the catalog."
    )
    result = _strip_feature_catalog_paragraphs(text)
    assert "A/1/1538" not in result
    assert "Citations in a [@author]" not in result
    assert "Zoom to" not in result
    assert "Intro prose about the method." in result
    assert "More prose after the catalog." in result


def test_strip_feature_catalog_paragraphs_leaves_normal_prose_untouched():
    text = "MEMIT edits factual associations in GPT-J using a closed-form update."
    assert _strip_feature_catalog_paragraphs(text) == text


def test_strip_feature_catalog_paragraphs_leaves_isolated_slash_text_untouched():
    # A bare ID-shaped or link-shaped paragraph with no catalog neighbors on
    # both sides isn't part of a triple — leave it (and its neighbors) alone.
    text = "Intro.\n\nSee reference A/1/1538 in the appendix.\n\nOutro."
    assert _strip_feature_catalog_paragraphs(text) == text


def test_extract_file_strips_feature_catalog_before_chunking(kg, vault):
    text = (
        "A/1/1538\n\n"
        "Citations in a [@author] or [@authoryear] format\n\n"
        "Zoom to [↗ View details](<https://transformer-circuits.pub/2023/monosemantic-features/vis/a1.html#feature-1538>)"
    )
    f = vault.root / "notes" / "test.md"
    f.write_text(f"---\ntype: note\n---\nIntro prose.\n\n{text}\n\nOutro prose.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    with _patch_create(kg, return_value=result) as mock_create, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    sent_prompt = mock_create.call_args.kwargs["messages"][1]["content"]
    assert "A/1/1538" not in sent_prompt
    assert "Intro prose." in sent_prompt or "Outro prose." in sent_prompt


# ── Extraction + upsert ───────────────────────────────────────────────────────

def test_extract_file_upserts_nodes(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\n# Title\nSome content about neural networks.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "test_neural_networks", "label": "Neural Networks"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        changed = kg._extract_file(f, "note")

    assert changed is True
    result = kg._conn.execute("MATCH (e:Entity) RETURN e.id, e.trust_tier")
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    assert ["test_neural_networks", "note"] in rows


def test_extract_file_upserts_edges(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: source\n---\nPaper A relates to Paper B.", encoding="utf-8")
    result = _extraction(
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        edges=[{"source": "a", "target": "b", "relation": "cites", "confidence": "EXTRACTED"}],
    )

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "source")

    query = kg._conn.execute("MATCH (a:Entity)-[r:RelatesTo]->(b:Entity) RETURN a.id, r.relation, b.id")
    rows = []
    while query.has_next():
        rows.append(query.get_next())
    assert ["a", "cites", "b"] in rows


def test_extract_file_skips_call_when_lease_denied(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")

    with _patch_create(kg) as mock_create, \
         patch("prisma.services.resource_lock.acquire", return_value=(False, None, None)), \
         patch("prisma.services.resource_lock.backoff.retry_with_backoff",
               side_effect=lambda attempt, is_success, **kw: attempt()):
        kg._extract_file(f, "note")

    assert not mock_create.called


def test_extract_file_does_not_advance_manifest_when_lease_denied(kg, vault):
    # Real bug this guards against: a file that changed while Ollama/the
    # compute pool was unreachable must not be marked processed — otherwise
    # it's silently never retried unless it changes again (roadmap.md's
    # Ollama resilience item).
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")

    with _patch_create(kg), \
         patch("prisma.services.resource_lock.acquire", return_value=(False, None, None)), \
         patch("prisma.services.resource_lock.backoff.retry_with_backoff",
               side_effect=lambda attempt, is_success, **kw: attempt()):
        changed = kg._extract_file(f, "note")

    assert changed is False
    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is None


def test_extract_file_retries_after_connection_error_on_next_call(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")

    with _patch_create(kg, side_effect=ConnectionError("down")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is None

    good = _extraction(nodes=[{"id": "ok", "label": "OK"}])
    with _patch_create(kg, return_value=good), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        changed = kg._extract_file(f, "note")

    assert changed is True
    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is not None


def test_extract_file_advances_manifest_when_section_legitimately_finds_nothing(kg, vault):
    # A successful call that finds no entities is not the same as a failed
    # call — it must still count as "processed" so it isn't retried forever.
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")
    empty = _extraction(nodes=[], edges=[])

    with _patch_create(kg, return_value=empty), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        changed = kg._extract_file(f, "note")

    assert changed is False  # nothing to upsert
    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is not None  # but genuinely processed, not retried


def test_extract_file_stops_remaining_sections_after_one_chunk_fails(kg, vault):
    # Real behavior change (2026-07-05, per cservinl): a failed chunk now
    # stops the rest of *this file*'s sections rather than letting them
    # keep running — no point spending GPU time on sections belonging to a
    # file that's getting tainted and fully re-extracted next cycle anyway.
    # extraction_concurrency=1 makes this deterministic in the test: with
    # exactly one worker, sections run strictly in submission order, so a
    # failure on the first one guarantees no later one has started yet.
    kg._token_budget = 1500
    kg._extraction_concurrency = 1
    f = vault.root / "notes" / "test.md"
    body = "# One\n" + ("First section content. " * 400) + "\n# Two\n" + ("Second section content. " * 400)
    f.write_text(f"---\ntype: note\n---\n{body}", encoding="utf-8")
    good = _extraction(nodes=[{"id": "ok", "label": "OK"}])
    call_count = {"n": 0}

    def _side_effect(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ValueError("bad response")
        return good

    with _patch_create(kg, side_effect=_side_effect), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        changed = kg._extract_file(f, "note")

    assert changed is False
    assert call_count["n"] == 1  # remaining sections never attempted
    result = kg._conn.execute("MATCH (e:Entity {id: 'ok'}) RETURN e.id")
    assert not result.has_next()
    with kg._lock:
        assert f in kg._pending  # tainted — retried on the next background cycle


def test_extract_file_survives_extraction_call_raising(kg, vault):
    # Regression: response parsing/validation used to run outside the
    # request try/except, so a malformed response raised unhandled inside
    # the thread-pool worker instead of being treated as "this section
    # failed, retry next cycle" like every other failure mode in
    # _call_ollama_extract. Instructor's own retry-exhaustion exception
    # (or any other failure it raises) must be handled the same way.
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")

    with _patch_create(kg, side_effect=ValueError("validation failed")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        changed = kg._extract_file(f, "note")

    assert changed is False
    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is None


# ── Incremental caching ───────────────────────────────────────────────────────

def test_extract_file_skips_unchanged_content(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSame content.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a", "label": "A"}])

    with _patch_create(kg, return_value=result) as mock_create, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        first = kg._extract_file(f, "note")
        calls_after_first = mock_create.call_count
        second = kg._extract_file(f, "note")

    assert first is True
    assert second is False
    assert mock_create.call_count == calls_after_first  # no new calls on unchanged content


def test_extract_file_reextracts_on_content_change(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nOriginal.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a", "label": "A"}])

    with _patch_create(kg, return_value=result) as mock_create, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")
        calls_after_first = mock_create.call_count
        f.write_text("---\ntype: note\n---\nCompletely different text now.", encoding="utf-8")
        changed = kg._extract_file(f, "note")

    assert changed is True
    assert mock_create.call_count > calls_after_first


# ── Deletion ──────────────────────────────────────────────────────────────────

def test_delete_file_removes_nodes(kg, vault):
    f = vault.root / "notes" / "gone.md"
    f.write_text("---\ntype: note\n---\nContent.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "gone_node", "label": "Gone"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    assert kg._delete_file(f) is True
    query = kg._conn.execute("MATCH (e:Entity {id: 'gone_node'}) RETURN e.id")
    assert not query.has_next()
    with kg._lock:
        assert kg._indexed_hash("notes/gone.md") is None


# ── Rename ────────────────────────────────────────────────────────────────────

def test_rename_file_relabels_without_reextracting(kg, vault):
    old = vault.root / "notes" / "old-name.md"
    old.write_text("---\ntype: note\n---\nContent.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "moved_node", "label": "Moved"}])

    with _patch_create(kg, return_value=result) as mock_create, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(old, "note")
        calls_before_move = mock_create.call_count

        new = vault.root / "notes" / "new-name.md"
        old.rename(new)
        assert kg._rename_file(old, new) is True

        # The entity survives under the new path, with no extra extraction
        # call -- a rename must not trigger re-extraction of unchanged content.
        assert mock_create.call_count == calls_before_move

    query = kg._conn.execute("MATCH (e:Entity {id: 'moved_node'}) RETURN e.source_file")
    assert query.has_next()
    assert query.get_next()[0] == "notes/new-name.md"
    with kg._lock:
        assert kg._indexed_hash("notes/old-name.md") is None
        assert kg._indexed_hash("notes/new-name.md") is not None


def test_rename_file_returns_false_when_old_path_was_never_indexed(kg, vault):
    old = vault.root / "notes" / "never-indexed.md"
    new = vault.root / "notes" / "still-never-indexed.md"
    assert kg._rename_file(old, new) is False


def test_drain_once_refreshes_surprising_connections_cache_after_a_rename(kg, vault):
    # A successful relabel rewrites source_file on the graph rows but queues
    # nothing for _process_pending -- the surprising_connections cache (and
    # its grounding Sources: header) would otherwise keep serving the
    # pre-rename path as a dead slug.
    a = vault.root / "notes" / "a.md"
    a.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    b = vault.root / "notes" / "b.md"
    b.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    a_result = _extraction(
        nodes=[{"id": "a", "label": "A"}, {"id": "a_bridge", "label": "Bridge"}],
        edges=[{"source": "a", "target": "a_bridge", "relation": "cites"}],
    )
    b_result = _extraction(
        nodes=[{"id": "c", "label": "C"}, {"id": "b_bridge", "label": "Bridge"}],
        edges=[{"source": "b_bridge", "target": "c", "relation": "extends"}],
    )
    with _patch_create(kg, side_effect=[a_result, b_result]), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(a, "note")
        kg._extract_file(b, "note")
    kg._refresh_top_entities()
    kg._refresh_surprising_connections()
    assert "notes/a.md" in {kg.surprising_connections()[0].source_file_a,
                            kg.surprising_connections()[0].source_file_b}

    moved = vault.root / "notes" / "a-renamed.md"
    a.rename(moved)
    with kg._lock:
        kg._pending_renames.append((a, moved))
    kg._drain_once()

    srcs = {kg.surprising_connections()[0].source_file_a,
            kg.surprising_connections()[0].source_file_b}
    assert "notes/a.md" not in srcs
    assert "notes/a-renamed.md" in srcs


def test_timeline_releases_the_lock_before_reading_frontmatter(kg, vault):
    # The graph scan holds self._lock; the per-document frontmatter reads
    # must not, or a broad timeline query stalls the indexer + every KG
    # request for the whole scan+read.
    (vault.root / "sources").mkdir(parents=True, exist_ok=True)
    (vault.root / "sources" / "p.md").write_text(
        "---\ntype: source\nyear: 2011\n---\nbody", encoding="utf-8")
    with kg._lock:
        kg._upsert("sources/p.md", "source", [{"id": "p_topic", "label": "Topic"}], [])

    locked_during_read: list[bool] = []
    real = vault.frontmatter_for_relpath

    def spy(rel):
        locked_during_read.append(kg._lock.locked())
        return real(rel)

    with patch.object(vault, "frontmatter_for_relpath", side_effect=spy):
        entries = kg.timeline("topic")

    assert entries and entries[0].year == 2011
    assert locked_during_read and not any(locked_during_read)


def test_loop_survives_a_failing_drain_cycle(kg):
    # A Kùzu stream error (or any exception) in one incremental cycle must
    # not kill the daemon thread and stop all further indexing.
    cycles = []

    def flaky():
        cycles.append(len(cycles))
        if len(cycles) == 1:
            raise RuntimeError("kùzu stream died mid-cycle")
        kg._stop_event.set()

    kg._drain_once = flaky
    with patch.object(kg, "_full_index"), patch.object(kg._stop_event, "wait"):
        kg._stop_event.clear()
        kg._loop()

    assert cycles == [0, 1]  # ran again after the failure instead of dying


def test_drain_once_requeues_the_batch_when_processing_fails(kg, vault):
    # _loop() catches -- a failed cycle must not silently drop the queued
    # work, or the graph stays stale until an unrelated FS event.
    f = vault.root / "notes" / "x.md"
    f.write_text("---\ntype: note\n---\nc", encoding="utf-8")
    with kg._lock:
        kg._pending.add(f)

    with patch.object(kg, "_process_pending", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            kg._drain_once()

    with kg._lock:
        assert f in kg._pending
    assert kg.status().state == "stale"


# ── Trust tier ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("node_type,expected_tier", [
    ("source", "source"),
    ("note", "note"),
    ("chat", "chat"),
    ("stream", "note"),
])
def test_trust_tier_for_maps_node_type(kg, vault, node_type, expected_tier):
    f = vault.root / "x.md"
    f.write_text(f"---\ntype: {node_type}\n---\ncontent", encoding="utf-8")
    assert kg._trust_tier_for(f) == expected_tier


def test_trust_tier_defaults_to_note_when_unreadable(kg, vault):
    missing = vault.root / "does-not-exist.md"
    assert kg._trust_tier_for(missing) == "note"


# ── Retrieval ─────────────────────────────────────────────────────────────────

def test_search_ranks_by_term_match(kg, vault):
    f1 = vault.root / "notes" / "a.md"
    f1.write_text("---\ntype: note\n---\nAbout neural networks.", encoding="utf-8")
    f2 = vault.root / "notes" / "b.md"
    f2.write_text("---\ntype: note\n---\nAbout cooking recipes.", encoding="utf-8")
    result_a = _extraction(nodes=[{"id": "a_neural_networks", "label": "Neural Networks"}])
    result_b = _extraction(nodes=[{"id": "b_recipes", "label": "Recipes"}])

    with _patch_create(kg, side_effect=[result_a, result_b]), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f1, "note")
        kg._extract_file(f2, "note")

    results = kg.search("neural networks")
    assert results
    assert results[0].source_file == "notes/a.md"


def test_search_excludes_chat_trust_tier(kg, vault):
    f = vault.root / "chats" / "conversation.md"
    f.write_text("---\ntype: chat\n---\nDiscussed neural networks here.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "chat_neural_networks", "label": "Neural Networks"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "chat")

    # search_vault-equivalent must never surface chat content — see TODO.md
    # "Chat trust tiers" section.
    assert kg.search("neural networks") == []


def test_search_returns_empty_for_no_matching_terms(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a_thing", "label": "Thing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    assert kg.search("completely unrelated query xyz") == []


def test_request_path_retrieval_scans_hold_the_connection_lock(kg):
    # Kùzu's connection is not thread-safe and FastAPI runs these sync
    # handlers concurrently (with each other and with background-index
    # upserts). Every live scan on self._conn must hold self._lock -- the
    # same lock the extraction upserts take. Recorded at execute() time.
    real = kg._conn
    lock = kg._lock
    held: list[bool] = []

    class _LockSpyConn:
        def execute(self, *a, **k):
            held.append(lock.locked())
            return real.execute(*a, **k)

        def __getattr__(self, name):
            return getattr(real, name)

    kg._conn = _LockSpyConn()

    # the scans still on the request path (god_nodes/authors/vault_health are
    # now cache-only reads -- see _refresh_derived_caches)
    kg.search("anything")
    kg.expand_node("missing-id")
    kg.timeline("anything")
    kg.entities_for_file("notes/x.md")
    kg._refresh_derived_caches()  # the background refresh must hold it too

    assert held and all(held)


# ── top_entities (vault-overview priming block) ────────────────────────────────

def test_compute_top_entities_ranks_by_undirected_degree(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(
        nodes=[{"id": "hub", "label": "Hub"}, {"id": "leaf1", "label": "Leaf 1"}, {"id": "leaf2", "label": "Leaf 2"}],
        edges=[{"source": "hub", "target": "leaf1"}, {"source": "hub", "target": "leaf2"}],
    )

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    kg._refresh_top_entities()
    top = kg.top_entities()
    assert top[0].id == "hub"
    assert top[0].degree == 2


def test_compute_top_entities_excludes_chat_trust_tier_on_either_endpoint(kg, vault):
    note_file = vault.root / "notes" / "a.md"
    note_file.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    note_result = _extraction(
        nodes=[{"id": "real_entity", "label": "Real Entity"}, {"id": "other_real", "label": "Other Real"}],
        edges=[{"source": "real_entity", "target": "other_real"}],
    )
    chat_file = vault.root / "chats" / "c.md"
    chat_file.write_text("---\ntype: chat\n---\ncontent", encoding="utf-8")
    chat_result = _extraction(
        nodes=[{"id": "chat_entity", "label": "Chat Entity"}],
        edges=[{"source": "real_entity", "target": "chat_entity"}],
    )

    with _patch_create(kg, side_effect=[note_result, chat_result]), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(note_file, "note")
        kg._extract_file(chat_file, "chat")

    kg._refresh_top_entities()
    top = kg.top_entities()
    real = next(e for e in top if e.id == "real_entity")
    assert real.degree == 1  # only the other_real edge counts, not the chat_entity one
    assert all(e.id != "chat_entity" for e in top)


def test_top_entities_returns_cached_slice_without_querying_kuzu(kg):
    kg._top_entities_cache = [TopEntity(id="x", label="X", degree=5)]
    with patch.object(kg._conn, "execute") as mock_execute:
        result = kg.top_entities()
    assert result == [TopEntity(id="x", label="X", degree=5)]
    mock_execute.assert_not_called()


def test_full_index_refreshes_top_entities_cache(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        edges=[{"source": "a", "target": "b"}],
    )

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._full_index()

    assert kg.top_entities() != []


def test_drop_index_clears_top_entities_cache(kg, vault):
    kg._top_entities_cache = [TopEntity(id="x", label="X", degree=5)]

    with patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch.object(kg, "_full_index"):  # avoid the real background re-index racing this assertion
        kg.drop_index()

    assert kg.top_entities() == []


# ── surprising_connections (background-cached, like top_entities above) ────────

def test_surprising_connections_returns_cached_slice_without_querying_kuzu(kg):
    kg._surprising_connections_cache = [
        SurprisingConnection(entity_a="a", entity_b="c", bridge="b", relation_a="cites", relation_b="extends", score=0.8),
    ]
    with patch.object(kg._conn, "execute") as mock_execute:
        result = kg.surprising_connections()
    assert result[0].bridge == "b"
    mock_execute.assert_not_called()


def test_refresh_surprising_connections_populates_cache_from_two_documents(kg, vault):
    # Sequential, deterministic _extract_file calls (not _full_index()'s
    # concurrent path -- side_effect order isn't guaranteed to match file
    # order once extraction fans out across threads).
    a_file = vault.root / "notes" / "a.md"
    a_file.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    b_file = vault.root / "notes" / "b.md"
    b_file.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    # Distinct ids ("a_bridge"/"b_bridge") with a shared label, matching
    # what real extraction actually produces (see kg_queries.
    # surprising_connections' docstring) -- reusing one literal "bridge" id
    # across both files would be the same physical node touched twice, not
    # two documents' separate instances of a shared concept, and now gets
    # correctly excluded rather than falsely counted as a bridge.
    a_result = _extraction(
        nodes=[{"id": "a", "label": "A"}, {"id": "a_bridge", "label": "Bridge"}],
        edges=[{"source": "a", "target": "a_bridge", "relation": "cites"}],
    )
    b_result = _extraction(
        nodes=[{"id": "c", "label": "C"}, {"id": "b_bridge", "label": "Bridge"}],
        edges=[{"source": "b_bridge", "target": "c", "relation": "extends"}],
    )

    with _patch_create(kg, side_effect=[a_result, b_result]), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(a_file, "note")
        kg._extract_file(b_file, "note")

    # 4 entities of degree 1 -- none is a hub, so nothing is excluded.
    kg._refresh_surprising_connections()

    links = kg.surprising_connections()
    assert links and links[0].bridge == "Bridge"


def test_refresh_surprising_connections_excludes_a_hub_past_the_top_15(kg):
    # d1_bridge is a genuine hub (degree 6) but ranks #16 -- below the
    # 15-slot priming cache. It must still be hub-excluded as a bridge.
    with kg._lock:
        for h in range(15):  # 15 fillers, degree 10 each -- they fill the top-15
            kg._upsert(f"notes/f{h}.md", "note",
                       [{"id": f"f{h}", "label": f"F{h}"}] + [{"id": f"f{h}_{i}", "label": "L"} for i in range(10)],
                       [{"source": f"f{h}", "target": f"f{h}_{i}", "relation": "r"} for i in range(10)])
        # doc1: concept A -> "Bridge" instance d1_bridge, which is also a hub
        kg._upsert("notes/d1.md", "note",
                   [{"id": "d1_a", "label": "A"}, {"id": "d1_bridge", "label": "Bridge"}]
                   + [{"id": f"d1_l{i}", "label": "L"} for i in range(5)],
                   [{"source": "d1_a", "target": "d1_bridge", "relation": "cites"}]
                   + [{"source": "d1_bridge", "target": f"d1_l{i}", "relation": "r"} for i in range(5)])
        # doc2: concept C -> a second "Bridge" instance (not a hub)
        kg._upsert("notes/d2.md", "note",
                   [{"id": "d2_c", "label": "C"}, {"id": "d2_bridge", "label": "Bridge"}],
                   [{"source": "d2_bridge", "target": "d2_c", "relation": "extends"}])

    kg._refresh_top_entities()
    assert all(e.id != "d1_bridge" for e in kg.top_entities())  # confirms it's past the top-15
    kg._refresh_surprising_connections()

    assert all(link.bridge != "Bridge" for link in kg.surprising_connections(limit=100))


class _CountingLock:
    """Wraps a real lock, counting `with` entries -- so a test can assert a
    refresh scans and publishes under one hold, with no gap a concurrent
    drop_index() could slip a graph-clear into."""

    def __init__(self, real):
        self._real = real
        self.entries = 0

    def __enter__(self):
        self.entries += 1
        return self._real.__enter__()

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_refresh_top_entities_scans_and_publishes_under_one_lock_hold(kg):
    with kg._lock:
        kg._upsert("notes/a.md", "note",
                   [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                   [{"source": "a", "target": "b", "relation": "cites"}])
    kg._lock = _CountingLock(kg._lock)

    kg._refresh_top_entities()

    assert kg._lock.entries == 1
    assert kg.top_entities()


def test_refresh_surprising_connections_scans_and_publishes_under_one_lock_hold(kg):
    with kg._lock:
        kg._upsert("notes/a.md", "note",
                   [{"id": "a", "label": "A"}, {"id": "a_bridge", "label": "Bridge"}],
                   [{"source": "a", "target": "a_bridge", "relation": "cites"}])
        kg._upsert("notes/c.md", "note",
                   [{"id": "c", "label": "C"}, {"id": "c_bridge", "label": "Bridge"}],
                   [{"source": "c_bridge", "target": "c", "relation": "extends"}])
    kg._refresh_top_entities()
    kg._lock = _CountingLock(kg._lock)

    kg._refresh_surprising_connections()

    assert kg._lock.entries == 1
    assert kg.surprising_connections()


def test_refresh_surprising_connections_cache_holds_more_than_the_top_entities_slice(kg):
    # The cache must be populated up to the real maximum a /graph request can
    # ask for (SURPRISING_CONNECTIONS_MAX), not silently capped at
    # TOP_ENTITIES_CACHE_SIZE by inheriting kg_queries.surprising_connections'
    # own default limit. kg_queries' limit slicing is already covered by
    # test_kg_queries.py::test_surprising_connections_respects_limit -- this
    # asserts the cache itself, not the slice, was the bottleneck.
    for i in range(20):
        with kg._lock:
            kg._upsert(f"notes/a{i}.md", "note",
                       [{"id": f"a{i}", "label": f"A{i}"}, {"id": f"a{i}_bridge", "label": f"Bridge{i}"}],
                       [{"source": f"a{i}", "target": f"a{i}_bridge", "relation": "cites"}])
            kg._upsert(f"notes/b{i}.md", "note",
                       [{"id": f"c{i}", "label": f"C{i}"}, {"id": f"b{i}_bridge", "label": f"Bridge{i}"}],
                       [{"source": f"b{i}_bridge", "target": f"c{i}", "relation": "extends"}])

    kg._refresh_top_entities()
    kg._refresh_surprising_connections()

    assert len(kg.surprising_connections(limit=100)) > TOP_ENTITIES_CACHE_SIZE


def test_drop_index_clears_surprising_connections_cache(kg):
    kg._surprising_connections_cache = [
        SurprisingConnection(entity_a="a", entity_b="c", bridge="b", relation_a="cites", relation_b="extends", score=0.8),
    ]

    with patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch.object(kg, "_full_index"):  # avoid the real background re-index racing this assertion
        kg.drop_index()

    assert kg.surprising_connections() == []


# ── god_nodes / authors / vault_health (background-cached, like above) ─────────

def _seed_graph(kg):
    with kg._lock:
        kg._upsert("sources/a.md", "source",
                   [{"id": "hub", "label": "Hub", "author": "Ada Lovelace"},
                    {"id": "leaf", "label": "Leaf"},
                    {"id": "lonely", "label": "Lonely"}],
                   [{"source": "hub", "target": "leaf", "relation": "cites"}])


def test_god_nodes_authors_vault_health_are_cache_only_reads(kg):
    kg._god_nodes_cache = [TopEntity(id="h", label="H", degree=3)]
    kg._authors_cache = [AuthorSummary(author="Ada", file_count=1)]
    kg._vault_health_cache = VaultHealthResponse(
        orphans=[OrphanEntity(id="o", label="O")], orphan_count=1)
    kg._suggest_questions_cache = [
        SuggestedQuestion(question="What connects 'A' and 'B'?", grounding_source_file="notes/a.md"),
    ]

    with patch.object(kg._conn, "execute") as mock_execute:
        assert kg.god_nodes()[0].id == "h"
        assert kg.authors()[0].author == "Ada"
        assert kg.vault_health().orphan_count == 1
        assert kg.suggest_questions()[0].grounding_source_file == "notes/a.md"
    mock_execute.assert_not_called()


def test_refresh_derived_caches_populates_the_new_caches(kg):
    _seed_graph(kg)

    kg._refresh_derived_caches()

    assert any(e.id == "hub" for e in kg.god_nodes())
    assert any(a.author == "Ada Lovelace" for a in kg.authors())
    assert any(o.id == "lonely" for o in kg.vault_health().orphans)
    assert any(q.grounding_source_file == "sources/a.md" for q in kg.suggest_questions())
    assert "Hub" in kg._entity_labels_cache


def test_drop_index_clears_suggest_questions_cache(kg):
    kg._suggest_questions_cache = [
        SuggestedQuestion(question="What connects 'A' and 'B'?", grounding_source_file="notes/a.md"),
    ]
    kg._entity_labels_cache = ["A", "B"]

    with patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch.object(kg, "_full_index"):  # avoid the real background re-index racing this assertion
        kg.drop_index()

    assert kg.suggest_questions() == []
    assert kg._entity_labels_cache == []


def test_refresh_suggest_questions_scans_and_publishes_under_one_lock_hold(kg):
    with kg._lock:
        kg._upsert("notes/a.md", "note",
                   [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                   [{"source": "a", "target": "b", "relation": "cites"}])
    kg._lock = _CountingLock(kg._lock)

    kg._refresh_suggest_questions()

    assert kg._lock.entries == 1
    assert kg.suggest_questions()


def test_refresh_entity_labels_scans_and_publishes_under_one_lock_hold(kg):
    with kg._lock:
        kg._upsert("notes/a.md", "note", [{"id": "a", "label": "A"}], [])
    kg._lock = _CountingLock(kg._lock)

    kg._refresh_entity_labels()

    assert kg._lock.entries == 1
    assert kg._entity_labels_cache == ["A"]


# ── graph_relevance (lightweight stream-triage design) ─────────────────────────

def test_graph_relevance_scores_text_overlap_against_cached_labels(kg):
    kg._entity_labels_cache = ["Neural Networks", "Transformers"]

    results = kg.graph_relevance(["A paper about Neural Networks and Transformers", "Unrelated topic"])

    assert results[0].score == 2
    assert set(results[0].matched_entities) == {"Neural Networks", "Transformers"}
    assert results[1].score == 0
    assert results[1].matched_entities == []


def test_graph_relevance_is_case_insensitive(kg):
    kg._entity_labels_cache = ["Neural Networks"]
    assert kg.graph_relevance(["neural networks are great"])[0].score == 1


def test_graph_relevance_does_not_match_a_short_label_inside_an_unrelated_word(kg):
    # A bare substring check (an earlier version of this method, caught in
    # self-review rather than by the original test suite) matches "AI"
    # inside "explain", "US" inside "custom", "ROC" inside "process" --
    # none of these texts are actually about any of these entities.
    kg._entity_labels_cache = ["AI", "US", "ROC"]
    results = kg.graph_relevance(["I will explain this later", "a custom setup", "the process was smooth"])
    assert [r.score for r in results] == [0, 0, 0]


def test_graph_relevance_still_matches_a_short_label_as_a_whole_word(kg):
    kg._entity_labels_cache = ["AI"]
    assert kg.graph_relevance(["real AI research"])[0].score == 1


def test_graph_relevance_matches_a_label_starting_or_ending_in_punctuation(kg):
    # Plain `\b` (a second self-review round caught this one) fails on any
    # label that itself starts/ends with punctuation -- there's never a
    # word/non-word *transition* at a position surrounded by punctuation
    # and whitespace on both sides, even though the label is verbatim in
    # the text.
    kg._entity_labels_cache = [".NET", "Ph.D.", "C++", "e.g.", "U.S."]
    results = kg.graph_relevance([
        "built on .NET", "she earned her Ph.D. last year", "we compared C++ vs Rust",
        "e.g. this example", "the U.S. government",
    ])
    assert [r.score for r in results] == [1, 1, 1, 1, 1]


def test_graph_relevance_dedupes_case_variant_labels_from_different_documents(kg):
    # Two documents can independently extract "Neural Networks" and
    # "neural networks" as separate cache entries -- both are the same
    # concept and must not double the score or duplicate the match list.
    kg._entity_labels_cache = ["Neural Networks", "neural networks"]
    result = kg.graph_relevance(["a paper about neural networks"])[0]
    assert result.score == 1
    assert result.matched_entities == ["Neural Networks"]


def test_graph_relevance_scores_each_text_independently_and_preserves_order(kg):
    kg._entity_labels_cache = ["X"]
    results = kg.graph_relevance(["has X", "no match", "also has X"])
    assert [r.score for r in results] == [1, 0, 1]


def test_graph_relevance_empty_label_cache_scores_everything_zero(kg):
    kg._entity_labels_cache = []
    assert kg.graph_relevance(["anything"]) == [GraphRelevance(score=0, matched_entities=[])]


def test_graph_relevance_is_a_cache_only_read_no_kuzu_call(kg):
    kg._entity_labels_cache = ["X"]
    with patch.object(kg._conn, "execute") as mock_execute:
        kg.graph_relevance(["has X"])
    mock_execute.assert_not_called()


def test_vault_health_slices_orphans_but_keeps_the_true_count(kg):
    kg._vault_health_cache = VaultHealthResponse(
        orphans=[OrphanEntity(id=f"o{i}", label=f"O{i}") for i in range(10)],
        orphan_count=10,
    )
    resp = kg.vault_health(limit=3)
    assert len(resp.orphans) == 3
    assert resp.orphan_count == 10


def test_drop_index_clears_the_new_derived_caches(kg):
    # populate the caches from a real graph, then drop -- the cache-only
    # readers would otherwise keep serving the pre-drop rows.
    _seed_graph(kg)
    kg._refresh_derived_caches()
    assert kg.god_nodes() and kg.authors() and kg.vault_health().orphans

    with patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch.object(kg, "_full_index"):
        kg.drop_index()

    assert kg.god_nodes() == []
    assert kg.authors() == []
    assert kg.vault_health().orphan_count == 0


# ── Status / lifecycle ────────────────────────────────────────────────────────

def test_status_starts_stale(vault, tmp_path):
    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out")
    status = service.status()
    assert status.state == "stale"
    assert status.last_indexed is None
    assert status.last_error is None
    assert status.current_activity is None


def test_full_index_clears_activity_when_done(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a_thing", "label": "Thing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._full_index()

    assert kg.status().current_activity is None


def test_extract_file_sets_activity_during_extraction(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a_thing", "label": "Thing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch.object(kg, "_set_activity", wraps=kg._set_activity) as mock_set_activity:
        kg._extract_file(f, "note")

    activities = [c.args[0] for c in mock_set_activity.call_args_list]
    assert any(a and "extracting notes/a.md" in a for a in activities)


def test_mark_stale_does_not_override_indexing_state(kg):
    with kg._lock:
        kg._state = "indexing"
    kg.mark_stale()
    assert kg.status().state == "indexing"


def test_mark_stale_ignores_stream_paths(kg, vault):
    # Regression test for a real 2026-07-25 bug: streams/*.yaml is excluded
    # from the KG's own file watcher (_VaultChangeHandler never adds it to
    # _pending), so calling mark_stale() for a stream write set "stale" with
    # nothing ever able to clear it -- stuck forever. Confirmed live on
    # a test server right after the vault-sync engine pushed a stream file.
    with kg._lock:
        kg._state = "idle"
    kg.mark_stale(vault.root / "streams" / "my-topic.yaml")
    assert kg.status().state == "idle"


def test_mark_stale_still_applies_to_md_paths(kg, vault):
    with kg._lock:
        kg._state = "idle"
    kg.mark_stale(vault.root / "notes" / "a.md")
    assert kg.status().state == "stale"


def test_is_relevant_path_matches_watcher_exclusions(kg, vault):
    assert kg.is_relevant_path(vault.root / "notes" / "a.md") is True
    assert kg.is_relevant_path(vault.root / "streams" / "my-topic.yaml") is False
    assert kg.is_relevant_path(vault.root / ".vault-files" / "chromadb" / "x.json") is False
    assert kg.is_relevant_path(vault.root / ".hidden.md") is False


def test_process_pending_clears_stale_even_with_no_real_change(kg, vault):
    # Regression test for a real 2026-07-25 bug: mark_stale() is called
    # optimistically from many API call sites ahead of this watcher-driven
    # pass, so if the flagged file's content hash turns out unchanged (e.g.
    # a rewrite with identical content -- exactly what the vault-sync
    # engine's conflict-retry path does), "stale" stayed stuck forever with
    # nothing left to process, since only the real-change branch used to
    # clear it.
    f = vault.root / "notes" / "a.md"
    content = "---\ntype: note\n---\ncontent"
    f.write_text(content, encoding="utf-8")
    with kg._lock:
        kg._state = "stale"
        rel = str(f.relative_to(vault.root))
        kg._set_indexed_hash(rel, hashlib.sha256(content.encode("utf-8")).hexdigest())

    kg._process_pending({f})

    assert kg.status().state == "idle"


def test_process_pending_refreshes_caches_on_deletion_only_batch(kg, vault):
    # A pending set with nothing left to extract (every path already gone
    # from disk) must still refresh top_entities/surprising_connections --
    # _extract_files_concurrently([]) can't itself detect that a deletion
    # is what actually changed the graph this cycle.
    f = vault.root / "notes" / "gone.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(
        nodes=[{"id": "gone_a", "label": "A"}, {"id": "gone_b", "label": "B"}],
        edges=[{"source": "gone_a", "target": "gone_b", "relation": "cites"}],
    )
    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")
    kg._refresh_top_entities()
    assert kg.top_entities()  # sanity: the cache holds the soon-to-be-deleted entity

    f.unlink()
    kg._process_pending({f})

    assert kg.top_entities() == []


def test_full_index_sets_idle_and_last_indexed(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a_thing", "label": "Thing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._full_index()

    status = kg.status()
    assert status.state == "idle"
    assert status.last_indexed is not None
    assert status.last_error is None


# ── Knowledge Graph progress page ─────────────────────────────────────────────

def test_full_index_resets_sync_progress_when_done(kg, vault):
    # sync_total=0 after completion means "no active full sync" to the UI —
    # distinct from a genuine "0 of N done" mid-sync state.
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a_thing", "label": "Thing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._full_index()

    status = kg.status()
    assert status.sync_total == 0
    assert status.sync_done == 0
    assert status.current_file is None


def test_extract_files_concurrently_skips_all_when_generation_is_stale(kg, vault):
    # Simulates drop_index() having bumped _index_generation after this
    # call's generation was captured — nothing should be submitted at all.
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")

    with patch.object(kg, "_extract_file") as mock_extract_file:
        changed = kg._extract_files_concurrently([f], generation=kg._index_generation - 1)

    assert changed == 0
    assert not mock_extract_file.called


def test_drop_index_clears_graph_and_resets_progress_state(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a_thing", "label": "Thing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    query = kg._conn.execute("MATCH (e:Entity {id: 'a_thing'}) RETURN e.id")
    assert query.has_next()

    with patch.object(kg, "_full_index"):  # avoid spawning a real reindex thread in the test
        kg.drop_index()

    query = kg._conn.execute("MATCH (e:Entity {id: 'a_thing'}) RETURN e.id")
    assert not query.has_next()
    status = kg.status()
    assert status.state == "stale"
    assert status.sync_total == 0
    assert status.sync_done == 0
    assert status.current_file is None


def test_drop_index_bumps_index_generation(kg):
    before = kg._index_generation
    with patch.object(kg, "_full_index"):
        kg.drop_index()
    assert kg._index_generation == before + 1


def test_full_index_tracks_progress_while_running(kg, vault):
    # Real bug this guards against: progress must be visible *during* a
    # full index, not just correctly reset once it's done — patch
    # _extract_files_concurrently to capture sync_total/on_file_done
    # behavior mid-run without needing a slow multi-file real extraction.
    f1 = vault.root / "notes" / "a.md"
    f1.write_text("---\ntype: note\n---\ncontent one", encoding="utf-8")
    f2 = vault.root / "notes" / "b.md"
    f2.write_text("---\ntype: note\n---\ncontent two", encoding="utf-8")
    seen_total = {}

    def fake_extract_files_concurrently(paths, on_file_done=None, generation=None):
        seen_total["sync_total"] = kg.status().sync_total
        if on_file_done:
            on_file_done(paths[0])
            seen_total["sync_done_after_one"] = kg.status().sync_done
        return 0

    with patch.object(kg, "_extract_files_concurrently", side_effect=fake_extract_files_concurrently):
        kg._full_index()

    assert seen_total["sync_total"] == 2
    assert seen_total["sync_done_after_one"] == 1


def test_full_index_sync_total_excludes_already_indexed_files(kg, vault):
    # Real bug this guards against: a fresh restart always walks every vault
    # file (a changed/new file must never be missed), but most files already
    # succeeded last time and are an instant hash-check skip — no real work.
    # Counting those toward sync_total made "X of Y" wildly misleading (e.g.
    # "0 of 102" on every restart even when only a couple of files actually
    # need real extraction). sync_total must reflect only files whose
    # content hash doesn't match what's already indexed.
    already_indexed = vault.root / "notes" / "already.md"
    already_indexed.write_text("---\ntype: note\n---\nUnchanged content.", encoding="utf-8")
    needs_work = vault.root / "notes" / "new.md"
    needs_work.write_text("---\ntype: note\n---\nBrand new content.", encoding="utf-8")

    rel = str(already_indexed.relative_to(vault.root))
    content_hash = hashlib.sha256(already_indexed.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    with kg._lock:
        kg._set_indexed_hash(rel, content_hash)

    seen_total = {}

    def fake_extract_files_concurrently(paths, on_file_done=None, generation=None):
        seen_total["sync_total"] = kg.status().sync_total
        return 0

    with patch.object(kg, "_extract_files_concurrently", side_effect=fake_extract_files_concurrently):
        kg._full_index()

    assert seen_total["sync_total"] == 1


def test_extract_file_tracks_current_file_chunk_progress(kg, vault):
    kg._token_budget = 1500
    f = vault.root / "notes" / "test.md"
    body = "# One\n" + ("First section content. " * 400) + "\n# Two\n" + ("Second section content. " * 400)
    f.write_text(f"---\ntype: note\n---\n{body}", encoding="utf-8")
    result = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    status = kg.status()
    # Extraction finished, so chunks_done should have reached the total —
    # current_file itself is only meaningful mid-extraction (not cleared
    # here, since _extract_file doesn't clear it — only _full_index does).
    assert status.current_file_chunks_total > 0
    assert status.current_file_chunks_done == status.current_file_chunks_total


def test_call_ollama_extract_records_chunk_duration(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    status = kg.status()
    assert status.chunk_duration_samples == 1
    assert status.chunk_avg_duration_ms is not None
    assert status.chunk_avg_duration_ms >= 0


def test_chunk_avg_duration_is_none_when_no_calls_made_yet(kg):
    status = kg.status()
    assert status.chunk_avg_duration_ms is None
    assert status.chunk_duration_samples == 0


def test_call_ollama_extract_records_chunk_size(kg, vault):
    f = vault.root / "notes" / "test.md"
    section = "word " * 40  # ~200 chars -> ~50 estimated tokens (len//4)
    f.write_text(f"---\ntype: note\n---\n{section}", encoding="utf-8")
    result = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    status = kg.status()
    assert status.chunk_avg_size_tokens is not None
    assert status.chunk_avg_size_tokens > 0


def test_chunk_avg_size_is_none_when_no_calls_made_yet(kg):
    status = kg.status()
    assert status.chunk_avg_size_tokens is None


def test_call_ollama_extract_tracks_instructor_retry_count(kg, vault):
    # Simulate what Instructor itself does internally on a validation
    # failure: fire the hooks object's parse:error event before eventually
    # succeeding. Our mock stands in for Instructor's real retry loop here.
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")
    good = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    def _side_effect(*a, **kw):
        hooks = kw["hooks"]
        hooks.emit_parse_error(ValueError("bad json"), attempt_number=1, max_attempts=3, is_last_attempt=False)
        hooks.emit_parse_error(ValueError("bad json"), attempt_number=2, max_attempts=3, is_last_attempt=False)
        return good

    with _patch_create(kg, side_effect=_side_effect), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    status = kg.status()
    assert status.chunk_avg_retries == 2


def test_dropped_chunk_recorded_in_memory_and_on_disk(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content that will fail extraction.", encoding="utf-8")

    with _patch_create(kg, side_effect=ValueError("validation retries exhausted")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    status = kg.status()
    assert status.dropped_chunks_total == 1
    assert len(status.dropped_chunks_recent) == 1
    dropped = status.dropped_chunks_recent[0]
    assert dropped.source_file == "notes/test.md"
    assert "validation retries exhausted" in dropped.error
    assert dropped.dead_letter_path is not None
    dead_letter = Path(dropped.dead_letter_path)
    assert dead_letter.exists()
    content = dead_letter.read_text(encoding="utf-8")
    assert "notes/test.md" in content
    assert "Some content that will fail extraction." in content


def test_dropped_chunk_summarizes_multiline_error_but_keeps_full_detail_on_disk(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content that will fail extraction.", encoding="utf-8")

    # Shaped like a real InstructorRetryException.__str__() — a multi-page
    # dump of every failed generation, ending in a <last_exception> block.
    # Confirmed live 2026-07-07: this broke the dead-letter file's fixed
    # 5-line header (the raw error was spliced directly into it) and dumped
    # the whole thing into the KG progress page's dropped-chunks table cell.
    multiline_error = (
        "<failed_attempts>\n<generation number=\"1\">\n...\n</generation>\n</failed_attempts>\n\n"
        "<last_exception>\n"
        "    1 validation error for Extraction\n"
        "  Invalid JSON: unexpected end of hex escape at line 29 column 45 "
        "[type=json_invalid, input_value='...', input_type=str]\n"
        "    For further information visit https://errors.pydantic.dev/2.12/v/json_invalid\n"
        "</last_exception>\n"
    )

    with _patch_create(kg, side_effect=ValueError(multiline_error)), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    status = kg.status()
    dropped = status.dropped_chunks_recent[0]
    assert "\n" not in dropped.error
    assert "unexpected end of hex escape" in dropped.error
    assert "<failed_attempts>" not in dropped.error

    dead_letter = Path(dropped.dead_letter_path)
    content = dead_letter.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0].startswith("# source_file:")
    assert lines[1].startswith("# reason:")
    assert lines[2].startswith("# error:")
    assert "\n" not in lines[2]
    assert lines[3].startswith("# retries:")
    assert lines[4].startswith("# time:")
    # full raw error preserved verbatim in the body, and the chunk content
    # is still findable after it (not lost inside the error dump)
    assert "<failed_attempts>" in content
    assert "Some content that will fail extraction." in content


def test_dropped_chunks_total_is_zero_when_nothing_failed(kg):
    status = kg.status()
    assert status.dropped_chunks_total == 0
    assert status.dropped_chunks_recent == []


def test_list_dead_letters_returns_header_fields_without_clearing(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content that will fail extraction.", encoding="utf-8")

    with _patch_create(kg, side_effect=ValueError("validation retries exhausted")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    dead_letter = Path(kg.status().dropped_chunks_recent[0].dead_letter_path)

    entries = kg.list_dead_letters()

    assert len(entries) == 1
    assert entries[0].file == dead_letter.name
    assert entries[0].source_file == "notes/test.md"
    assert "validation retries exhausted" in entries[0].error
    # read-only — the file and in-memory counters are untouched
    assert dead_letter.exists()
    assert kg.status().dropped_chunks_total == 1


def test_list_dead_letters_returns_empty_when_none_exist(kg):
    assert kg.list_dead_letters() == []


def test_clear_dead_letters_removes_files_and_resets_counters(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content that will fail extraction.", encoding="utf-8")

    with _patch_create(kg, side_effect=ValueError("validation retries exhausted")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    dead_letter = Path(kg.status().dropped_chunks_recent[0].dead_letter_path)
    assert dead_letter.exists()

    removed = kg.clear_dead_letters()

    assert removed == 1
    assert not dead_letter.exists()
    status = kg.status()
    assert status.dropped_chunks_total == 0
    assert status.dropped_chunks_recent == []


def test_clear_dead_letters_returns_zero_when_none_exist(kg):
    assert kg.clear_dead_letters() == 0


# ── taint_file ──────────────────────────────────────────────────────────────

def test_taint_file_returns_false_for_nonexistent_file(kg):
    assert kg.taint_file("notes/does-not-exist.md") is False


def test_taint_file_clears_tracking_and_enqueues_existing_file(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content about neural networks.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "test_neural_networks", "label": "Neural Networks"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    assert kg._indexed_hash("notes/test.md") is not None  # extraction tracked it

    tainted = kg.taint_file("notes/test.md")

    assert tainted is True
    assert kg._indexed_hash("notes/test.md") is None  # tracking cleared
    assert f in kg._pending  # enqueued for re-extraction


# ── entities_for_file ─────────────────────────────────────────────────────

def test_entities_for_file_returns_nodes_and_edges(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: source\n---\nPaper A relates to Paper B.", encoding="utf-8")
    result = _extraction(
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        edges=[{"source": "a", "target": "b", "relation": "cites", "confidence": "EXTRACTED"}],
    )

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "source")

    data = kg.entities_for_file("notes/test.md")

    entity_ids = {e.id for e in data.entities}
    assert entity_ids == {"a", "b"}
    assert len(data.edges) == 1
    assert data.edges[0].source == "a"
    assert data.edges[0].target == "b"
    assert data.edges[0].relation == "cites"


def test_entities_for_file_empty_for_untracked_file(kg):
    data = kg.entities_for_file("notes/never-extracted.md")
    assert data.entities == []
    assert data.edges == []


# ── query (compatibility wrapper over search()) ────────────────────────────

def test_query_returns_text_summary_of_matching_entities(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nContent about quantum computing.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "quantum_computing", "label": "Quantum Computing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    results = kg.query("quantum")

    assert len(results) == 1
    assert "notes/test.md" in results[0].text


def test_query_returns_empty_when_no_matches(kg):
    assert kg.query("nothing indexed matches this") == []


def test_query_sources_are_slugs_not_raw_paths(kg, vault):
    # ADR-017: `sources` must be vault slugs (what a Footnote's `sources`
    # list expects) -- and the compound dir--name form, not the bare stem,
    # so a duplicate filename in another folder stays distinct.
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nContent about quantum computing.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "quantum_computing", "label": "Quantum Computing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    results = kg.query("quantum")

    assert results[0].sources == ["notes--test"]


def test_query_sources_dedup_multiple_entities_from_same_file(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nQuantum computing and quantum entanglement.", encoding="utf-8")
    result = _extraction(nodes=[
        {"id": "quantum_computing", "label": "Quantum Computing"},
        {"id": "quantum_entanglement", "label": "Quantum Entanglement"},
    ])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    results = kg.query("quantum")

    assert results[0].sources == ["notes--test"]
