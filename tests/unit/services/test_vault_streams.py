"""
Unit tests for vault-based stream CRUD (VaultService).
Uses a real tmp_path — no mocks needed, VaultService is purely file-based.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import Stream, StreamStatus, RefreshFrequency


@pytest.fixture
def vault(tmp_path: Path) -> VaultService:
    v = VaultService(tmp_path)
    v.ensure_dirs()
    return v


class TestCreateStream:
    def test_returns_stream_with_correct_fields(self, vault):
        s = vault.create_stream(title="XAI Research", query="explainable AI")
        assert s.title == "XAI Research"
        assert s.query == "explainable AI"
        assert s.slug == "xai-research"
        assert s.status == StreamStatus.active
        assert s.refresh_frequency == RefreshFrequency.weekly
        assert s.total_papers == 0

    def test_yaml_file_written(self, vault):
        vault.create_stream(title="My Stream", query="test")
        files = list(vault.root.rglob("*.yaml"))
        assert any(f.stem == "my-stream" for f in files)

    def test_optional_fields(self, vault):
        s = vault.create_stream(
            title="Tagged", query="q", description="desc", tags=["ai", "ml"], refresh_frequency="daily"
        )
        assert s.description == "desc"
        assert s.refresh_frequency == RefreshFrequency.daily

    def test_slug_collision_generates_unique_slug(self, vault):
        s1 = vault.create_stream(title="Deep Learning", query="q1")
        s2 = vault.create_stream(title="Deep Learning", query="q2")
        assert s1.slug != s2.slug
        assert s2.slug == "deep-learning-1"

    def test_slug_collision_increments(self, vault):
        vault.create_stream(title="Foo", query="q")
        vault.create_stream(title="Foo", query="q")
        s3 = vault.create_stream(title="Foo", query="q")
        assert s3.slug == "foo-2"


class TestGetStream:
    def test_get_existing(self, vault):
        vault.create_stream(title="Neural Nets", query="neural networks")
        s = vault.get_stream("neural-nets")
        assert s.title == "Neural Nets"
        assert s.query == "neural networks"

    def test_get_missing_raises(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.get_stream("does-not-exist")

    def test_get_is_case_insensitive_on_slug(self, vault):
        vault.create_stream(title="My Topic", query="q")
        s = vault.get_stream("My-Topic")
        assert s.slug == "my-topic"


class TestListStreams:
    def test_empty_vault_returns_empty_list(self, vault):
        assert vault.list_streams() == []

    def test_lists_all_created_streams(self, vault):
        vault.create_stream(title="A", query="qa")
        vault.create_stream(title="B", query="qb")
        streams = vault.list_streams()
        assert len(streams) == 2
        slugs = {s.slug for s in streams}
        assert "a" in slugs
        assert "b" in slugs

    def test_ignores_non_yaml_files_in_streams_dir(self, vault):
        from prisma.storage.models.vault_models import NodeType
        vault.create_stream(title="Real", query="q")
        (vault.default_dirs[NodeType.stream] / "junk.txt").write_text("x")
        streams = vault.list_streams()
        assert len(streams) == 1


class TestSaveStream:
    def test_updates_fields(self, vault):
        vault.create_stream(title="Draft", query="q")
        s = vault.save_stream("draft", status="paused", total_papers=5)
        assert s.status == StreamStatus.paused
        assert s.total_papers == 5

    def test_persists_across_reload(self, vault):
        vault.create_stream(title="Persist", query="q")
        vault.save_stream("persist", total_papers=42)
        reloaded = vault.get_stream("persist")
        assert reloaded.total_papers == 42

    def test_saves_datetime_as_isoformat(self, vault):
        vault.create_stream(title="Dt", query="q")
        now = datetime(2026, 1, 15, 12, 0, 0)
        s = vault.save_stream("dt", last_updated=now)
        assert s.last_updated is not None
        assert s.last_updated.year == 2026

    def test_missing_stream_raises(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.save_stream("ghost", total_papers=1)

    def test_none_value_removes_key(self, vault):
        vault.create_stream(title="Nullify", query="q", description="old desc")
        s = vault.save_stream("nullify", description=None)
        assert s.description is None


class TestDeleteStream:
    def test_deletes_file(self, vault):
        vault.create_stream(title="Temp", query="q")
        vault.delete_stream("temp")
        assert vault.list_streams() == []

    def test_delete_missing_raises(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.delete_stream("nothing")

    def test_get_after_delete_raises(self, vault):
        vault.create_stream(title="Gone", query="q")
        vault.delete_stream("gone")
        with pytest.raises(FileNotFoundError):
            vault.get_stream("gone")


class TestAppendStreamLog:
    def test_appends_entry(self, vault):
        vault.create_stream(title="Log Test", query="q")
        vault.append_stream_log("log-test", "found 3 papers")
        vault.append_stream_log("log-test", "found 1 paper")

        import yaml
        path = vault._find_stream_path("log-test")
        data = yaml.safe_load(path.read_text())
        assert len(data["log"]) == 2
        assert data["log"][0]["entry"] == "found 3 papers"
        assert data["log"][1]["entry"] == "found 1 paper"

    def test_append_to_missing_stream_is_silent(self, vault):
        vault.append_stream_log("no-such-slug", "entry")  # must not raise
