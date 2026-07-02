"""Unit tests for prisma.server.supervisor.ResourceManager.

Covers the compute-pool lease model: capacity limiting, release paths
(explicit, by-worker on restart, and the PID/timeout-based reaper), and
status reporting. See ADR-012.
"""
import os
import time
from pathlib import Path

from prisma.server.supervisor import ResourceManager, _load_compute_pools


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
    r2, rid2 = rm.acquire("api", pid, model="qwen2.5-graphify:7b")

    assert r2 is None and rid2 is None


def test_model_affinity_allows_switch_once_pool_drains():
    rm = ResourceManager({"local-ollama": 3}, model_affinity={"local-ollama"})
    pid = os.getpid()

    resource, request_id = rm.acquire("api", pid, model="qwen2.5:7b")
    rm.release(resource, request_id)

    r2, rid2 = rm.acquire("api", pid, model="qwen2.5-graphify:7b")
    assert r2 == "local-ollama" and rid2 is not None
    assert rm.status()["local-ollama"]["active_model"] == "qwen2.5-graphify:7b"


def test_model_affinity_reaper_clears_active_model_when_lease_dies():
    rm = ResourceManager({"local-ollama": 3}, model_affinity={"local-ollama"})
    dead_pid = 2**30

    rm.acquire("api", dead_pid, model="qwen2.5:7b")
    rm.reap()

    assert rm.status()["local-ollama"]["active_model"] is None
    r2, rid2 = rm.acquire("api", os.getpid(), model="qwen2.5-graphify:7b")
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

    capacity, affinity = _load_compute_pools()

    assert capacity == {"local-ollama": 3, "cloud_api": 4}
    assert affinity == {"local-ollama"}


def test_load_compute_pools_defaults_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    capacity, affinity = _load_compute_pools()

    assert capacity == {"default": 1}
    assert affinity == {"default"}  # zero-config default assumes one local GPU


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

    capacity, affinity = _load_compute_pools()

    assert affinity == {"local-ollama"}


# ── contention stats: "why is the server busy" without grepping logs ────────

def test_stats_count_grants_and_capacity_denials():
    rm = ResourceManager({"default": 1})
    pid = os.getpid()

    rm.acquire("api", pid)   # granted
    rm.acquire("api", pid)   # denied — full

    stats = rm.status()["default"]["stats"]
    assert stats == {"granted": 1, "denied_capacity": 1, "denied_model_busy": 0}


def test_stats_count_model_busy_denials_separately_from_capacity():
    rm = ResourceManager({"local-ollama": 3}, model_affinity={"local-ollama"})
    pid = os.getpid()

    rm.acquire("api", pid, model="qwen2.5:7b")               # granted
    rm.acquire("api", pid, model="qwen2.5-graphify:7b")      # denied — different model, pool has room

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
    r2, _ = rm.acquire("api", pid, model="qwen2.5-graphify:7b")

    assert r1 == "remote-ollama" and r2 == "remote-ollama"
    assert rm.status()["remote-ollama"]["active_model"] is None
