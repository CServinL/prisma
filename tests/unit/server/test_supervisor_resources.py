"""Unit tests for prisma.server.supervisor.ResourceManager.

Covers the compute-pool lease model: capacity limiting, release paths
(explicit, by-worker on restart, and the PID/timeout-based reaper), and
status reporting. See ADR-012.
"""
import os
import time
from pathlib import Path
from unittest.mock import patch

from prisma.server.supervisor import ResourceManager, _load_compute_pools, _process_memory_mb, _system_info


def test_acquire_respects_pool_capacity():
    rm = ResourceManager({"default": 2})
    pid = os.getpid()

    r1, rid1 = rm.acquire("api", pid)
    r2, rid2 = rm.acquire("api", pid)
    r3, rid3 = rm.acquire("api", pid)

    assert r1 == "default" and rid1 is not None
    assert r2 == "default" and rid2 is not None
    assert r3 is None and rid3 is None


def test_acquire_specific_pool_and_first_free():
    rm = ResourceManager({"local": 1, "remote": 2})
    pid = os.getpid()

    # Request a specific pool
    r1, rid1 = rm.acquire("api", pid, pool="remote")
    assert r1 == "remote"

    # No pool specified — first with free capacity
    r2, rid2 = rm.acquire("api", pid)
    assert r2 in ("local", "remote")


def test_release_frees_capacity():
    rm = ResourceManager({"default": 1})
    pid = os.getpid()

    resource, request_id = rm.acquire("api", pid)
    assert resource == "default"
    assert rm.acquire("api", pid)[0] is None  # full

    rm.release(resource, request_id)
    resource2, _ = rm.acquire("api", pid)
    assert resource2 == "default"  # capacity freed


def test_release_all_held_by_clears_only_that_holder():
    rm = ResourceManager({"default": 2})
    pid = os.getpid()

    rm.acquire("api", pid)
    rm.acquire("web", pid)

    rm.release_all_held_by("api")
    status = rm.status()
    holders = [l["holder"] for l in status["default"]["leases"]]
    assert holders == ["web"]


def test_reap_releases_lease_with_dead_pid():
    rm = ResourceManager({"default": 1})
    dead_pid = 2**30  # exceedingly unlikely to be a real running pid

    rm.acquire("api", dead_pid)
    rm.reap()

    assert rm.status()["default"]["in_use"] == 0


def test_reap_keeps_lease_with_live_pid_and_no_timeout():
    rm = ResourceManager({"default": 1})
    pid = os.getpid()  # this test process — definitely alive

    rm.acquire("api", pid)
    rm.reap()

    assert rm.status()["default"]["in_use"] == 1


def test_reap_releases_lease_that_exceeded_its_timeout():
    rm = ResourceManager({"default": 1})
    pid = os.getpid()

    rm.acquire("api", pid, timeout=0.01)
    time.sleep(0.02)
    rm.reap()

    assert rm.status()["default"]["in_use"] == 0


def test_status_reports_capacity_and_held_for():
    rm = ResourceManager({"default": 3})
    pid = os.getpid()

    rm.acquire("api", pid)
    status = rm.status()

    assert status["default"]["capacity"] == 3
    assert status["default"]["in_use"] == 1
    assert status["default"]["leases"][0]["pid"] == pid
    assert status["default"]["leases"][0]["held_for_s"] >= 0


def test_status_reports_type_gpu_for_model_affinity_pool_and_cloud_otherwise():
    rm = ResourceManager({"local-ollama": 3, "openrouter": 8}, model_affinity={"local-ollama"})

    status = rm.status()

    assert status["local-ollama"]["type"] == "gpu"
    assert status["openrouter"]["type"] == "cloud"


# ── model_affinity: one resident model at a time, N concurrent within it ────

def test_model_affinity_grants_concurrent_leases_for_same_model():
    rm = ResourceManager({"local-ollama": 3}, model_affinity={"local-ollama"})
    pid = os.getpid()

    r1, rid1 = rm.acquire("api", pid, model="qwen2.5:7b")
    r2, rid2 = rm.acquire("api", pid, model="qwen2.5:7b")

    assert r1 == "local-ollama" and rid1 is not None
    assert r2 == "local-ollama" and rid2 is not None
    assert rm.status()["local-ollama"]["active_model"] == "qwen2.5:7b"


def test_model_affinity_denies_a_different_model_while_busy():
    rm = ResourceManager({"local-ollama": 3}, model_affinity={"local-ollama"})
    pid = os.getpid()

    rm.acquire("api", pid, model="qwen2.5:7b")
    r2, rid2 = rm.acquire("api", pid, model="prisma-kg:7b")

    assert r2 is None and rid2 is None


def test_model_affinity_allows_switch_once_pool_drains():
    rm = ResourceManager({"local-ollama": 3}, model_affinity={"local-ollama"})
    pid = os.getpid()

    resource, request_id = rm.acquire("api", pid, model="qwen2.5:7b")
    rm.release(resource, request_id)

    r2, rid2 = rm.acquire("api", pid, model="prisma-kg:7b")
    assert r2 == "local-ollama" and rid2 is not None
    assert rm.status()["local-ollama"]["active_model"] == "prisma-kg:7b"


def test_model_affinity_reaper_clears_active_model_when_lease_dies():
    rm = ResourceManager({"local-ollama": 3}, model_affinity={"local-ollama"})
    dead_pid = 2**30

    rm.acquire("api", dead_pid, model="qwen2.5:7b")
    rm.reap()

    assert rm.status()["local-ollama"]["active_model"] is None
    r2, rid2 = rm.acquire("api", os.getpid(), model="prisma-kg:7b")
    assert r2 == "local-ollama" and rid2 is not None


def test_load_compute_pools_reads_model_affinity_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = tmp_path / ".config" / "prisma"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "compute_pools:\n"
        "  - name: local-ollama\n"
        "    max_concurrent: 3\n"
        "    model_affinity: true\n"
        "  - name: cloud_api\n"
        "    max_concurrent: 4\n"
        "    model_affinity: false\n"
    )

    capacity, affinity, pool_models, model_concurrency, vram_budget, model_vram, model_background_limit = _load_compute_pools()

    assert capacity == {"local-ollama": 3, "cloud_api": 4}
    assert affinity == {"local-ollama"}
    assert pool_models == {"local-ollama": set(), "cloud_api": set()}


def test_load_compute_pools_defaults_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    capacity, affinity, pool_models, model_concurrency, vram_budget, model_vram, model_background_limit = _load_compute_pools()

    assert capacity == {"default": 1}
    assert affinity == {"default"}  # zero-config default assumes one local GPU
    assert pool_models == {"default": set()}


def test_load_compute_pools_model_affinity_defaults_true_unless_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = tmp_path / ".config" / "prisma"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "compute_pools:\n"
        "  - name: local-ollama\n"
        "    max_concurrent: 3\n"       # no model_affinity key — should default true
        "  - name: cloud_api\n"
        "    max_concurrent: 4\n"
        "    model_affinity: false\n"   # explicitly opted out — auto-scaled/auto-routed
    )

    capacity, affinity, pool_models, model_concurrency, vram_budget, model_vram, model_background_limit = _load_compute_pools()

    assert affinity == {"local-ollama"}


def test_load_compute_pools_type_field_is_authoritative_over_model_affinity(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = tmp_path / ".config" / "prisma"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "compute_pools:\n"
        "  - name: local-ollama\n"
        "    type: gpu\n"
        "    provider: ollama\n"
        "    models: [prisma-kg:7b, prisma-chat:7b]\n"
        "    max_concurrent: 3\n"
        "  - name: cloud_api\n"
        "    type: cloud\n"
        "    provider: openrouter\n"
        "    models: [anthropic/claude-3.5-sonnet]\n"
        "    max_concurrent: 8\n"
    )

    capacity, affinity, pool_models, model_concurrency, vram_budget, model_vram, model_background_limit = _load_compute_pools()

    assert capacity == {"local-ollama": 3, "cloud_api": 8}
    assert affinity == {"local-ollama"}
    assert pool_models == {
        "local-ollama": {"prisma-kg:7b", "prisma-chat:7b"},
        "cloud_api": {"anthropic/claude-3.5-sonnet"},
    }


# ── contention stats: "why is the server busy" without grepping logs ────────

def test_stats_count_grants_and_capacity_denials():
    rm = ResourceManager({"default": 1})
    pid = os.getpid()

    rm.acquire("api", pid)   # granted
    rm.acquire("api", pid)   # denied — full

    stats = rm.status()["default"]["stats"]
    assert stats == {"granted": 1, "denied_capacity": 1, "denied_model_busy": 0, "denied_vram_budget": 0}


def test_stats_count_model_busy_denials_separately_from_capacity():
    rm = ResourceManager({"local-ollama": 3}, model_affinity={"local-ollama"})
    pid = os.getpid()

    rm.acquire("api", pid, model="qwen2.5:7b")               # granted
    rm.acquire("api", pid, model="prisma-kg:7b")      # denied — different model, pool has room

    stats = rm.status()["local-ollama"]["stats"]
    assert stats["granted"] == 1
    assert stats["denied_model_busy"] == 1
    assert stats["denied_capacity"] == 0


def test_stats_are_cumulative_across_grant_release_cycles():
    rm = ResourceManager({"default": 1})
    pid = os.getpid()

    resource, request_id = rm.acquire("api", pid)
    rm.release(resource, request_id)
    rm.acquire("api", pid)

    assert rm.status()["default"]["stats"]["granted"] == 2


def test_pools_without_model_affinity_ignore_model_identity():
    rm = ResourceManager({"remote-ollama": 2})  # no model_affinity — plenty of GPUs
    pid = os.getpid()

    r1, _ = rm.acquire("api", pid, model="qwen2.5:7b")
    r2, _ = rm.acquire("api", pid, model="prisma-kg:7b")

    assert r1 == "remote-ollama" and r2 == "remote-ollama"
    assert rm.status()["remote-ollama"]["active_model"] is None


# ── Model-based pool auto-routing ─────────────────────────────────────────────

def test_acquire_auto_routes_by_declared_model():
    rm = ResourceManager(
        {"local-ollama": 3, "cloud_api": 8},
        model_affinity={"local-ollama"},
        pool_models={
            "local-ollama": {"prisma-kg:7b", "prisma-chat:7b"},
            "cloud_api": {"anthropic/claude-3.5-sonnet"},
        },
    )
    pid = os.getpid()

    r1, _ = rm.acquire("api", pid, model="anthropic/claude-3.5-sonnet")
    r2, _ = rm.acquire("kg", pid, model="prisma-kg:7b")

    assert r1 == "cloud_api"
    assert r2 == "local-ollama"


def test_acquire_cloud_model_never_lands_in_gpu_pool_even_when_gpu_pool_idle():
    # Regression guard for the exact scenario that motivated this feature:
    # an OpenRouter call must never get misattributed as "the GPU's resident
    # model" and start denying real local Ollama calls for no hardware reason.
    rm = ResourceManager(
        {"local-ollama": 3, "cloud_api": 8},
        model_affinity={"local-ollama"},
        pool_models={
            "local-ollama": {"prisma-kg:7b"},
            "cloud_api": {"anthropic/claude-3.5-sonnet"},
        },
    )
    pid = os.getpid()

    rm.acquire("api", pid, model="anthropic/claude-3.5-sonnet")
    r2, _ = rm.acquire("kg", pid, model="prisma-kg:7b")

    # The cloud call never touched local-ollama at all — its active_model
    # reflects only the legitimate local kg call, never the cloud model name.
    assert rm.status()["local-ollama"]["active_model"] == "prisma-kg:7b"
    assert r2 == "local-ollama"  # not denied


def test_acquire_falls_back_to_untyped_pool_when_model_not_declared_anywhere():
    rm = ResourceManager(
        {"local-ollama": 3, "misc": 2},
        pool_models={"local-ollama": {"prisma-kg:7b"}, "misc": set()},
    )
    pid = os.getpid()

    r, _ = rm.acquire("api", pid, model="some-other-model")

    assert r == "misc"


def test_acquire_falls_back_to_any_pool_when_no_pool_models_configured_at_all():
    # No pool_models passed at all — must behave exactly like before this
    # feature existed (every pre-existing caller that doesn't pass `pool`).
    rm = ResourceManager({"default": 1})
    pid = os.getpid()

    r, _ = rm.acquire("api", pid, model="anything")

    assert r == "default"


def test_acquire_explicit_pool_overrides_model_based_auto_routing():
    rm = ResourceManager(
        {"local-ollama": 3, "cloud_api": 8},
        pool_models={"local-ollama": {"prisma-kg:7b"}, "cloud_api": {"anthropic/claude-3.5-sonnet"}},
    )
    pid = os.getpid()

    r, _ = rm.acquire("api", pid, pool="cloud_api", model="prisma-kg:7b")

    assert r == "cloud_api"  # explicit pool wins even though the model is declared elsewhere


# ── Per-model concurrency within one GPU pool ─────────────────────────────────

def test_per_model_concurrency_override_caps_below_pool_default():
    # prisma-kg:7b runs at a much bigger num_ctx than prisma-chat:7b, so it
    # gets a tighter concurrency ceiling on the same physical GPU pool.
    rm = ResourceManager(
        {"local-ollama": 3},
        model_affinity={"local-ollama"},
        model_concurrency={"local-ollama": {"prisma-kg:7b": 1}},
    )
    pid = os.getpid()

    r1, rid1 = rm.acquire("kg", pid, model="prisma-kg:7b")
    r2, rid2 = rm.acquire("kg", pid, model="prisma-kg:7b")

    assert r1 == "local-ollama"
    assert r2 is None  # denied at 1, even though the pool's own max_concurrent is 3


def test_per_model_concurrency_override_allows_above_default_for_a_different_model():
    rm = ResourceManager(
        {"local-ollama": 1},
        model_affinity={"local-ollama"},
        model_concurrency={"local-ollama": {"prisma-chat:7b": 3}},
    )
    pid = os.getpid()

    r1, _ = rm.acquire("api", pid, model="prisma-chat:7b")
    r2, _ = rm.acquire("api", pid, model="prisma-chat:7b")
    r3, _ = rm.acquire("api", pid, model="prisma-chat:7b")

    assert [r1, r2, r3] == ["local-ollama"] * 3  # all 3 granted despite pool default of 1


def test_model_without_override_falls_back_to_pool_default():
    rm = ResourceManager(
        {"local-ollama": 2},
        model_affinity={"local-ollama"},
        model_concurrency={"local-ollama": {"prisma-kg:7b": 1}},
    )
    pid = os.getpid()

    r1, _ = rm.acquire("api", pid, model="nomic-embed-text")
    r2, _ = rm.acquire("api", pid, model="nomic-embed-text")
    r3, _ = rm.acquire("api", pid, model="nomic-embed-text")

    assert [r1, r2] == ["local-ollama", "local-ollama"]
    assert r3 is None  # pool default (2) applies, no override for this model


def test_non_affinity_pool_ignores_model_concurrency_overrides():
    # Cloud pools can hold leases for several different models concurrently,
    # so per-model overrides would incorrectly count unrelated models'
    # leases against one model's budget — deliberately not applied here.
    rm = ResourceManager(
        {"cloud_api": 5},
        model_concurrency={"cloud_api": {"anthropic/claude-3.5-sonnet": 1}},
    )
    pid = os.getpid()

    r1, _ = rm.acquire("api", pid, model="anthropic/claude-3.5-sonnet")
    r2, _ = rm.acquire("api", pid, model="anthropic/claude-3.5-sonnet")

    assert r1 == "cloud_api" and r2 == "cloud_api"  # pool default (5) used, not the override


def test_load_compute_pools_parses_per_model_concurrency_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = tmp_path / ".config" / "prisma"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "compute_pools:\n"
        "  - name: local-ollama\n"
        "    type: gpu\n"
        "    max_concurrent: 3\n"
        "    models:\n"
        "      - name: prisma-kg:7b\n"
        "        max_concurrent: 1\n"
        "      - name: prisma-chat:7b\n"
        "        max_concurrent: 3\n"
        "      - nomic-embed-text\n"  # plain string form
    )

    capacity, affinity, pool_models, model_concurrency, vram_budget, model_vram, model_background_limit = _load_compute_pools()

    assert pool_models["local-ollama"] == {"prisma-kg:7b", "prisma-chat:7b", "nomic-embed-text"}
    assert model_concurrency["local-ollama"] == {"prisma-kg:7b": 1, "prisma-chat:7b": 3}


def test_load_compute_pools_parses_vram_budget_and_model_vram(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = tmp_path / ".config" / "prisma"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "compute_pools:\n"
        "  - name: local-ollama\n"
        "    type: gpu\n"
        "    max_concurrent: 3\n"
        "    vram_budget_mb: 14000\n"
        "    models:\n"
        "      - name: prisma-llm:7b\n"
        "        vram_mb: 7500\n"
        "      - name: nomic-embed-text\n"
        "        vram_mb: 1000\n"
        "  - name: cloud_api\n"
        "    type: cloud\n"
        "    max_concurrent: 8\n"
    )

    capacity, affinity, pool_models, model_concurrency, vram_budget, model_vram, model_background_limit = _load_compute_pools()

    assert vram_budget == {"local-ollama": 14000, "cloud_api": None}
    assert model_vram["local-ollama"] == {"prisma-llm:7b": 7500, "nomic-embed-text": 1000}


# ── VRAM-budget-aware pools: models genuinely coexist when they fit ─────────

def test_acquire_admits_second_model_when_ollama_reports_room():
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        vram_budget={"local-ollama": 14000},
        model_vram={"local-ollama": {"prisma-llm:7b": 7500, "nomic-embed-text": 1000}},
    )
    pid = os.getpid()

    with patch("prisma.server.supervisor._query_ollama_resident_mb", return_value={"prisma-llm:7b": 7000}):
        r1, rid1 = rm.acquire("kg", pid, model="prisma-llm:7b")  # already resident per the mock
        r2, rid2 = rm.acquire("chroma", pid, model="nomic-embed-text")  # not yet resident, but fits

    assert r1 == "local-ollama" and rid1 is not None
    assert r2 == "local-ollama" and rid2 is not None


def test_acquire_denies_second_model_when_over_vram_budget():
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        vram_budget={"local-ollama": 8000},  # tight budget
        model_vram={"local-ollama": {"prisma-llm:7b": 7500, "some-other-model": 5000}},
    )
    pid = os.getpid()

    with patch("prisma.server.supervisor._query_ollama_resident_mb", return_value={"prisma-llm:7b": 7500}):
        r, rid = rm.acquire("api", pid, model="some-other-model")  # 7500 + 5000 > 8000

    assert r is None and rid is None
    assert rm.status()["local-ollama"]["stats"]["denied_vram_budget"] == 1


def test_acquire_grants_already_resident_model_regardless_of_new_model_cost():
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        vram_budget={"local-ollama": 8000},
        model_vram={"local-ollama": {"prisma-llm:7b": 7500}},
    )
    pid = os.getpid()

    with patch("prisma.server.supervisor._query_ollama_resident_mb", return_value={"prisma-llm:7b": 7500}):
        r, rid = rm.acquire("kg", pid, model="prisma-llm:7b")  # already resident — no budget math needed

    assert r == "local-ollama" and rid is not None


def test_acquire_falls_back_to_strict_affinity_when_ollama_unreachable():
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        vram_budget={"local-ollama": 14000},
        model_vram={"local-ollama": {"prisma-llm:7b": 7500, "nomic-embed-text": 1000}},
    )
    pid = os.getpid()

    with patch("prisma.server.supervisor._query_ollama_resident_mb", return_value=None):
        rm.acquire("kg", pid, model="prisma-llm:7b")
        r2, rid2 = rm.acquire("chroma", pid, model="nomic-embed-text")

    # Can't verify Ollama's real state — fails safe to strict single-model rule
    assert r2 is None and rid2 is None
    assert rm.status()["local-ollama"]["stats"]["denied_model_busy"] == 1


def test_acquire_per_model_concurrency_still_enforced_on_vram_budget_pool():
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        vram_budget={"local-ollama": 14000},
        model_concurrency={"local-ollama": {"prisma-llm:7b": 1}},
        model_vram={"local-ollama": {"prisma-llm:7b": 7500}},
    )
    pid = os.getpid()

    with patch("prisma.server.supervisor._query_ollama_resident_mb", return_value={}):
        r1, rid1 = rm.acquire("kg", pid, model="prisma-llm:7b")
        r2, rid2 = rm.acquire("chat", pid, model="prisma-llm:7b")  # same model, but over its own max_concurrent=1

    assert r1 == "local-ollama" and rid1 is not None
    assert r2 is None and rid2 is None


def test_status_reports_resident_models_and_vram_budget():
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        vram_budget={"local-ollama": 14000},
    )
    pid = os.getpid()

    with patch("prisma.server.supervisor._query_ollama_resident_mb", return_value={}):
        rm.acquire("kg", pid, model="prisma-llm:7b")
        rm.acquire("chroma", pid, model="nomic-embed-text")

    status = rm.status()["local-ollama"]
    assert status["resident_models"] == ["nomic-embed-text", "prisma-llm:7b"]
    assert status["vram_budget_mb"] == 14000


def test_status_reports_per_model_effective_capacity_not_flat_pool_default():
    # Regression guard: the flat "capacity" field is only the pool-wide
    # fallback (3 here) — a model with its own override (4) has a
    # different real ceiling, and showing the fallback instead is the
    # confusing display bug this field exists to fix.
    rm = ResourceManager(
        {"local-ollama": 3}, model_affinity={"local-ollama"},
        vram_budget={"local-ollama": 14000},
        model_concurrency={"local-ollama": {"prisma-llm:7b": 4}},
        model_background_limit={"local-ollama": {"prisma-llm:7b": 3}},
    )
    pid = os.getpid()

    with patch("prisma.server.supervisor._query_ollama_resident_mb", return_value={}):
        rm.acquire("kg", pid, model="prisma-llm:7b")

    model_capacity = rm.status()["local-ollama"]["model_capacity"]
    assert model_capacity["prisma-llm:7b"] == {"in_use": 1, "limit": 4, "background_limit": 3}


# ── Priority tiers: interactive must never queue behind background work ──────

def test_background_capped_below_full_concurrency_reserves_room_for_interactive():
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        model_background_limit={"local-ollama": {"prisma-llm:7b": 3}},
    )
    pid = os.getpid()

    r1, _ = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")
    r2, _ = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")
    r3, _ = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")
    r4, rid4 = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")  # 4th background — over its cap

    assert [r1, r2, r3] == ["local-ollama"] * 3
    assert r4 is None and rid4 is None


def test_interactive_still_granted_when_background_fills_its_own_cap():
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        model_background_limit={"local-ollama": {"prisma-llm:7b": 3}},
    )
    pid = os.getpid()

    rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")
    rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")
    rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")

    r_chat, rid_chat = rm.acquire("api", pid, model="prisma-llm:7b", priority="interactive")

    assert r_chat == "local-ollama" and rid_chat is not None  # uses the 4th slot background couldn't touch


def test_active_interactive_lease_does_not_shrink_backgrounds_own_quota():
    # Regression: background's admission check must count only *other
    # background* leases against background_max_concurrent, not interactive
    # ones too. Previously an active interactive lease counted toward the
    # total compared against the (smaller) background limit, so background
    # got denied one slot early — observed live as kg denied at
    # in_use=3/limit=3 with only 2 of those 3 leases actually being kg's.
    rm = ResourceManager(
        {"local-ollama": 6}, model_affinity={"local-ollama"},
        model_background_limit={"local-ollama": {"prisma-llm:7b": 3}},
    )
    pid = os.getpid()

    r_chat, _ = rm.acquire("api", pid, model="prisma-llm:7b", priority="interactive")
    assert r_chat == "local-ollama"

    r1, _ = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")
    r2, _ = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")
    r3, _ = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")

    assert [r1, r2, r3] == ["local-ollama"] * 3  # background still gets its full quota of 3


def test_background_denied_when_interactive_alone_fills_the_pool_to_full_capacity():
    # Regression: the fix above (background counts only its own leases) went
    # one step too far — it never checked background's request against the
    # pool's *total* real capacity at all. If interactive traffic alone has
    # already filled the pool to its full max_concurrent, a background
    # request would see background_in_use=0 (zero background leases so far)
    # and get granted anyway, pushing the pool past its configured ceiling.
    rm = ResourceManager(
        {"local-ollama": 6}, model_affinity={"local-ollama"},
        model_background_limit={"local-ollama": {"prisma-llm:7b": 3}},
    )
    pid = os.getpid()

    interactive_leases = [
        rm.acquire("api", pid, model="prisma-llm:7b", priority="interactive")
        for _ in range(6)
    ]
    assert all(r == "local-ollama" for r, _ in interactive_leases)  # fills the pool to its real max_concurrent

    r_bg, rid_bg = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")

    assert r_bg is None and rid_bg is None  # must not be granted just because background_in_use is 0


def test_interactive_defaults_to_background_priority_when_unspecified():
    # Existing callers (kg, chroma) that don't pass priority at all must
    # keep today's behavior — capped at the background limit, not the full
    # concurrency — so this reservation actually holds without every caller
    # needing to be updated.
    rm = ResourceManager(
        {"local-ollama": 4}, model_affinity={"local-ollama"},
        model_background_limit={"local-ollama": {"prisma-llm:7b": 3}},
    )
    pid = os.getpid()

    for _ in range(3):
        rm.acquire("kg", pid, model="prisma-llm:7b")  # no priority passed
    r4, rid4 = rm.acquire("kg", pid, model="prisma-llm:7b")

    assert r4 is None and rid4 is None


def test_no_background_limit_configured_uses_full_concurrency_for_both_tiers():
    rm = ResourceManager({"local-ollama": 2}, model_affinity={"local-ollama"})
    pid = os.getpid()

    r1, _ = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")
    r2, _ = rm.acquire("kg", pid, model="prisma-llm:7b", priority="background")

    assert r1 == "local-ollama" and r2 == "local-ollama"  # no reservation configured — unaffected


def test_load_compute_pools_parses_background_max_concurrent(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = tmp_path / ".config" / "prisma"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "compute_pools:\n"
        "  - name: local-ollama\n"
        "    type: gpu\n"
        "    max_concurrent: 4\n"
        "    models:\n"
        "      - name: prisma-llm:7b\n"
        "        background_max_concurrent: 3\n"
    )

    result = _load_compute_pools()
    model_background_limit = result[6]

    assert model_background_limit["local-ollama"] == {"prisma-llm:7b": 3}


# ── Memory/capacity reporting ─────────────────────────────────────────────────

def test_process_memory_mb_returns_positive_value_for_self():
    mb = _process_memory_mb(os.getpid())
    assert mb is not None
    assert mb > 0


def test_process_memory_mb_returns_none_for_nonexistent_pid():
    assert _process_memory_mb(2**30) is None


def test_system_info_reports_cpu_count_and_memory():
    info = _system_info()
    assert info["cpu_count"] and info["cpu_count"] > 0
    # memory fields may be None on non-Linux, but must be present as keys
    assert "memory_total_mb" in info
    assert "memory_available_mb" in info
