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
    _sanitize_escape_sequences,
    _strip_dense_data_paragraphs,
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


# ── Escape-sequence sanitization ──────────────────────────────────────────────
# Confirmed live 2026-07-07 (docs/kg-dead-letter-triage-2026-07-07.md): a real
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
# Confirmed live 2026-07-08 (docs/kg-dead-letter-triage-2026-07-07.md follow-up):
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
    assert results[0]["source_file"] == "notes/a.md"


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


# ── Status / lifecycle ────────────────────────────────────────────────────────

def test_status_starts_stale(vault, tmp_path):
    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out")
    status = service.status()
    assert status["state"] == "stale"
    assert status["last_indexed"] is None
    assert status["last_error"] is None
    assert status["current_activity"] is None


def test_full_index_clears_activity_when_done(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a_thing", "label": "Thing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._full_index()

    assert kg.status()["current_activity"] is None


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
    assert kg.status()["state"] == "indexing"


def test_full_index_sets_idle_and_last_indexed(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    result = _extraction(nodes=[{"id": "a_thing", "label": "Thing"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._full_index()

    status = kg.status()
    assert status["state"] == "idle"
    assert status["last_indexed"] is not None
    assert status["last_error"] is None


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
    assert status["sync_total"] == 0
    assert status["sync_done"] == 0
    assert status["current_file"] is None


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
    assert status["state"] == "stale"
    assert status["sync_total"] == 0
    assert status["sync_done"] == 0
    assert status["current_file"] is None


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
        seen_total["sync_total"] = kg.status()["sync_total"]
        if on_file_done:
            on_file_done(paths[0])
            seen_total["sync_done_after_one"] = kg.status()["sync_done"]
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
        seen_total["sync_total"] = kg.status()["sync_total"]
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
    assert status["current_file_chunks_total"] > 0
    assert status["current_file_chunks_done"] == status["current_file_chunks_total"]


def test_call_ollama_extract_records_chunk_duration(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "ok", "label": "OK"}])

    with _patch_create(kg, return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    status = kg.status()
    assert status["chunk_duration_samples"] == 1
    assert status["chunk_avg_duration_ms"] is not None
    assert status["chunk_avg_duration_ms"] >= 0


def test_chunk_avg_duration_is_none_when_no_calls_made_yet(kg):
    status = kg.status()
    assert status["chunk_avg_duration_ms"] is None
    assert status["chunk_duration_samples"] == 0


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
    assert status["chunk_avg_size_tokens"] is not None
    assert status["chunk_avg_size_tokens"] > 0


def test_chunk_avg_size_is_none_when_no_calls_made_yet(kg):
    status = kg.status()
    assert status["chunk_avg_size_tokens"] is None


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
    assert status["chunk_avg_retries"] == 2


def test_dropped_chunk_recorded_in_memory_and_on_disk(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content that will fail extraction.", encoding="utf-8")

    with _patch_create(kg, side_effect=ValueError("validation retries exhausted")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    status = kg.status()
    assert status["dropped_chunks_total"] == 1
    assert len(status["dropped_chunks_recent"]) == 1
    dropped = status["dropped_chunks_recent"][0]
    assert dropped["source_file"] == "notes/test.md"
    assert "validation retries exhausted" in dropped["error"]
    assert dropped["dead_letter_path"] is not None
    dead_letter = Path(dropped["dead_letter_path"])
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
    dropped = status["dropped_chunks_recent"][0]
    assert "\n" not in dropped["error"]
    assert "unexpected end of hex escape" in dropped["error"]
    assert "<failed_attempts>" not in dropped["error"]

    dead_letter = Path(dropped["dead_letter_path"])
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
    assert status["dropped_chunks_total"] == 0
    assert status["dropped_chunks_recent"] == []
