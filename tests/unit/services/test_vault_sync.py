"""Unit tests for VaultService's path-based access methods (read_by_path /
write_by_path / delete_by_path / list_md_manifest) — used by /sync/*.
Uses a real tmp_path, no mocks (same convention as test_vault_streams.py).
"""
from pathlib import Path

import pytest

from prisma.services.vault import VaultService


@pytest.fixture
def vault(tmp_path: Path) -> VaultService:
    v = VaultService(tmp_path)
    v.ensure_dirs()
    return v


def test_write_then_read_by_path_roundtrip(vault):
    mtime = vault.write_by_path("notes/foo.md", "# Foo\nhello")
    assert isinstance(mtime, float)
    body, read_mtime = vault.read_by_path("notes/foo.md")
    assert body == "# Foo\nhello"
    assert read_mtime == mtime


def test_write_by_path_creates_parent_dirs(vault):
    vault.write_by_path("deeply/nested/dir/note.md", "content")
    assert (vault.root / "deeply" / "nested" / "dir" / "note.md").is_file()


def test_write_by_path_overwrites_existing(vault):
    vault.write_by_path("notes/foo.md", "v1")
    vault.write_by_path("notes/foo.md", "v2")
    body, _ = vault.read_by_path("notes/foo.md")
    assert body == "v2"


def test_read_by_path_missing_file_returns_none(vault):
    assert vault.read_by_path("notes/does-not-exist.md") is None


def test_write_by_path_holds_vault_write_lock_for_its_whole_duration(vault, monkeypatch):
    # Regression: write_by_path()/delete_by_path() used to take a second,
    # separate _path_write_lock that was never coordinated with
    # _vault_write_lock -- a synced desktop edit landing on the same file
    # as a locked API-side edit (e.g. PATCH /{slug}/source) could still
    # race, just via two uncoordinated locks instead of no lock at all.
    import threading

    lock_held_during_call = threading.Event()
    proceed = threading.Event()
    real_write_text = Path.write_text

    # _safe_sync_path() runs BEFORE _vault_write_lock is acquired (same as
    # every other locked method resolves its path first) -- the write
    # itself, inside the lock, is the correct hook point.
    def blocking_write_text(self, data, encoding=None):
        lock_held_during_call.set()
        proceed.wait(timeout=2)
        return real_write_text(self, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", blocking_write_text)

    t = threading.Thread(target=lambda: vault.write_by_path("notes/foo.md", "content"))
    t.start()
    assert lock_held_during_call.wait(timeout=2), "write_by_path() never reached write_text()"

    acquired = vault._vault_write_lock.acquire(blocking=False)
    proceed.set()
    t.join()
    if acquired:
        vault._vault_write_lock.release()
    assert not acquired, "write_by_path() must hold _vault_write_lock while it runs"


def test_write_by_path_failed_write_preserves_the_existing_file(vault, monkeypatch):
    # Regression: the write was a plain write_text() (open-truncate-write,
    # not atomic) -- same defect class fixed on every other vault write
    # path.
    vault.write_by_path("notes/foo.md", "original content")

    original_write_text = Path.write_text

    def boom(self, data, encoding=None):
        original_write_text(self, "", encoding=encoding)
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(OSError):
        vault.write_by_path("notes/foo.md", "updated content")

    body, _ = vault.read_by_path("notes/foo.md")
    assert body == "original content"


def test_delete_by_path_removes_file(vault):
    vault.write_by_path("notes/foo.md", "content")
    vault.delete_by_path("notes/foo.md")
    assert vault.read_by_path("notes/foo.md") is None


def test_delete_by_path_missing_file_is_noop(vault):
    vault.delete_by_path("notes/never-existed.md")  # must not raise


def test_list_md_manifest_reflects_written_files(vault):
    vault.write_by_path("notes/a.md", "a")
    vault.write_by_path("notes/b.md", "bb")
    manifest = {path: (mtime, size) for path, mtime, size in vault.list_md_manifest()}
    assert set(manifest) == {"notes/a.md", "notes/b.md"}
    assert manifest["notes/b.md"][1] == 2


def test_write_by_path_accepts_stream_yaml(vault):
    mtime = vault.write_by_path("streams/my-topic.yaml", "title: My Topic\n")
    assert isinstance(mtime, float)
    body, read_mtime = vault.read_by_path("streams/my-topic.yaml")
    assert body == "title: My Topic\n"
    assert read_mtime == mtime


def test_yaml_outside_streams_dir_rejected(vault):
    with pytest.raises(ValueError):
        vault.write_by_path("notes/foo.yaml", "x")
    with pytest.raises(ValueError):
        vault.write_by_path("config.yaml", "x")


def test_non_yaml_inside_streams_dir_rejected(vault):
    with pytest.raises(ValueError):
        vault.write_by_path("streams/notes.txt", "x")


def test_list_md_manifest_includes_stream_yaml(vault):
    vault.write_by_path("notes/a.md", "a")
    vault.write_by_path("streams/my-topic.yaml", "title: My Topic\n")
    manifest = {path for path, _, _ in vault.list_md_manifest()}
    assert manifest == {"notes/a.md", "streams/my-topic.yaml"}


@pytest.mark.parametrize("bad_path", [
    "../outside.md",
    "notes/../../outside.md",
    "/etc/passwd.md",
])
def test_path_traversal_rejected(vault, bad_path):
    with pytest.raises(ValueError):
        vault.write_by_path(bad_path, "x")
    with pytest.raises(ValueError):
        vault.read_by_path(bad_path)
    with pytest.raises(ValueError):
        vault.delete_by_path(bad_path)


def test_non_md_extension_rejected(vault):
    with pytest.raises(ValueError):
        vault.write_by_path("notes/foo.txt", "x")


def test_reserved_dir_rejected(vault):
    with pytest.raises(ValueError):
        vault.write_by_path(".git/foo.md", "x")
    with pytest.raises(ValueError):
        vault.write_by_path("node_modules/foo.md", "x")


# ── resolve_within_root — the shared containment check _safe_sync_path and
# app.py's vault_asset route both go through (previously vault_asset had its
# own, independently-implemented, laxer abspath+prefix check) ───────────────

def test_resolve_within_root_accepts_nested_path(vault):
    resolved = vault.resolve_within_root("assets/logo.png")
    assert resolved == vault.root / "assets" / "logo.png"


@pytest.mark.parametrize("bad_path", [
    "../outside.png",
    "assets/../../outside.png",
    "/etc/passwd",
])
def test_resolve_within_root_rejects_traversal(vault, bad_path):
    with pytest.raises(ValueError):
        vault.resolve_within_root(bad_path)


def test_resolve_within_root_rejects_reserved_dirs(vault):
    # The exact gap the old vault_asset abspath-check had: a file under
    # .git/ or .vault-files/ would sail through a bare prefix check as long
    # as it stayed inside vault_root. This shared method rejects it outright.
    with pytest.raises(ValueError):
        vault.resolve_within_root(".git/config.png")
    with pytest.raises(ValueError):
        vault.resolve_within_root(".vault-files/kg-out/leak.png")


def test_resolve_within_root_rejects_symlink_escape(vault, tmp_path_factory):
    # A directory *inside* the vault that is itself a symlink pointing
    # outside it -- the string-based checks alone never call .resolve(),
    # so this would previously sail straight through them. `vault.root` is
    # `tmp_path` itself (see the `vault` fixture above), so "outside" must
    # be a genuinely separate tmp dir, not a subdirectory of it.
    outside = tmp_path_factory.mktemp("outside-the-vault")
    (outside / "secret.md").write_text("should not be reachable", encoding="utf-8")
    (vault.root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        vault.resolve_within_root("escape/secret.md")
